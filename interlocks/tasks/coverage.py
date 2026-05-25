"""Tests under coverage with threshold + uncovered listing."""

from __future__ import annotations

import sys

from interlocks import ui
from interlocks.config import (
    InterlockConfig,
    build_coverage_test_command,
    coverage_invoker_prefix,
    load_config,
    project_env_ready,
    project_env_skip_message,
    python_command_prefix,
)
from interlocks.defaults_path import has_project_config, path
from interlocks.runner import (
    Task,
    arg_flag_value,
    arg_value,
    fail_skip,
    run,
    run_task_json,
    warn_skip,
)
from interlocks.tasks.properties import (
    PROPERTY_PROFILES,
    _hypothesis_import_check_cmd,
    _properties_dir_arg,
    property_test_files,
)

_PROPERTY_PROFILE_SET = frozenset(PROPERTY_PROFILES)
_COVERAGE_APPEND_FLAG = "--append"
_PROPERTY_COVERAGE_RUNNER = """\
from hypothesis import settings
settings.register_profile('check', max_examples=15, deadline=None)
settings.register_profile('ci', max_examples=100, deadline=None)
settings.register_profile('nightly', max_examples=500, deadline=None)
import pytest
import sys
raise SystemExit(pytest.main(sys.argv[1:]))
"""


def _coverage_rcfile_args(cfg: InterlockConfig) -> list[str]:
    """``['--rcfile=<bundled>']`` when the project owns no coverage config, else ``[]``."""
    if has_project_config(cfg, "coverage", sidecars=(".coveragerc",)):
        return []
    return [f"--rcfile={path('coveragerc')}"]


def _coverage_import_check_cmd(cfg: InterlockConfig) -> list[str] | None:
    """Preflight non-uv projects where Interlocks cannot inject Coverage.py."""
    if cfg.test_invoker == "uv":
        return None
    message = (
        "interlocks: Coverage.py is not importable in the target Python environment. "
        f"Install `coverage>={cfg.tool_version('coverage')}` there, or use a uv-managed "
        "project so Interlocks can inject Coverage.py at runtime.\n"
    )
    code = (
        "import importlib.util, sys; "
        "ok = importlib.util.find_spec('coverage') is not None; "
        f"sys.stderr.write({message!r}) if not ok else None; "
        "raise SystemExit(0 if ok else 1)"
    )
    return [*python_command_prefix(cfg), "-c", code]


def _property_coverage_runner_path(cfg: InterlockConfig) -> str:
    return str(cfg.project_root / ".interlocks" / "property_coverage_runner.py")


def _write_property_coverage_runner_cmd(cfg: InterlockConfig) -> list[str]:
    code = (
        "from pathlib import Path; "
        f"path = Path({_property_coverage_runner_path(cfg)!r}); "
        "path.parent.mkdir(parents=True, exist_ok=True); "
        f"path.write_text({_PROPERTY_COVERAGE_RUNNER!r}, encoding='utf-8')"
    )
    return [*python_command_prefix(cfg), "-c", code]


def _coverage_property_test_command(
    cfg: InterlockConfig, *, coverage_args: tuple[str, ...], profile: str
) -> list[str]:
    properties_dir = _properties_dir_arg(cfg)
    return [
        *coverage_invoker_prefix(cfg),
        "coverage",
        "run",
        _COVERAGE_APPEND_FLAG,
        *coverage_args,
        _property_coverage_runner_path(cfg),
        properties_dir,
        "-q",
        f"--hypothesis-profile={profile}",
        *cfg.pytest_args,
    ]


def _property_coverage_pre_cmds(
    cfg: InterlockConfig, *, coverage_args: tuple[str, ...], profile: str
) -> tuple[list[str], ...]:
    if not property_test_files(cfg):
        return ()
    return (
        _hypothesis_import_check_cmd(cfg),
        _write_property_coverage_runner_cmd(cfg),
        _coverage_property_test_command(cfg, coverage_args=coverage_args, profile=profile),
    )


def task_coverage(
    *,
    min_pct: int | None = None,
    include_properties: bool = False,
    property_profile: str = "ci",
) -> Task | None:
    """Run tests under coverage and report against ``min_pct``.

    Precedence: explicit argument > ``--min=N`` on argv > ``cfg.coverage_min``.

    Returns ``None`` (after a ``warn_skip`` advisory) when a non-uv project has
    no in-tree ``.venv`` — running coverage against the installer's interpreter
    would produce an installer-dependent verdict, not a real finding.
    """
    cfg = load_config()
    if not project_env_ready(cfg):
        warn_skip(project_env_skip_message("coverage"))
        return None
    if min_pct is None:
        min_pct = _coverage_min_pct(cfg, min_pct)
    rcfile_args = _coverage_rcfile_args(cfg)
    run_cmd = build_coverage_test_command(cfg, coverage_args=tuple(rcfile_args))
    property_cmds = (
        _property_coverage_pre_cmds(
            cfg, coverage_args=tuple(rcfile_args), profile=property_profile
        )
        if include_properties
        else ()
    )
    # Only the progressive preset's baseline ratchet reads coverage.json; skip
    # the extra subprocess for everyone else.
    json_cmd: list[str] | None = None
    if cfg.preset == "progressive":
        json_path = cfg.project_root / ".interlocks" / "coverage.json"
        json_cmd = [
            *coverage_invoker_prefix(cfg),
            "coverage",
            "json",
            *rcfile_args,
            "-q",
            "-o",
            str(json_path),
        ]
    report_cmd = [
        *coverage_invoker_prefix(cfg),
        "coverage",
        "report",
        *rcfile_args,
        "--show-missing",
        f"--fail-under={min_pct}",
    ]
    pre_cmds = tuple(
        cmd
        for cmd in (_coverage_import_check_cmd(cfg), run_cmd, *property_cmds, json_cmd)
        if cmd is not None
    )
    display = f"coverage report --fail-under={min_pct}"
    if property_cmds:
        display += " + properties"
    return Task(
        f"Coverage >= {min_pct}%",
        report_cmd,
        pre_cmds=pre_cmds,
        test_summary=True,
        label="coverage",
        display=display,
        start_status="running" if property_cmds else None,
        progress_steps=_coverage_progress_steps(pre_cmds) if property_cmds else (),
    )


def _coverage_progress_steps(pre_cmds: tuple[list[str], ...]) -> tuple[str, ...]:
    return (*tuple(_coverage_progress_label(cmd) for cmd in pre_cmds), "coverage report")


def _coverage_progress_label(cmd: list[str]) -> str:
    joined = " ".join(cmd)
    if "Coverage.py is not importable" in joined:
        return "coverage import preflight"
    if "find_spec('hypothesis')" in joined:
        return "hypothesis import preflight"
    if "property_coverage_runner.py" in joined and "write_text" in joined:
        return "write property coverage runner"
    if _COVERAGE_APPEND_FLAG in cmd:
        return "property tests under coverage"
    if "json" in cmd:
        return "coverage JSON"
    return "unit tests under coverage"


def cmd_coverage(
    *,
    min_pct: int | None = None,
    include_properties: bool = False,
    property_profile: str = "ci",
    emit_json: bool = True,
) -> None:
    cfg = load_config()
    json_mode = emit_json and ui.is_json()
    resolved_min_pct, include_properties, property_profile = _coverage_options(
        cfg,
        min_pct=min_pct,
        include_properties=include_properties,
        property_profile=property_profile,
    )
    _validate_property_profile(property_profile, json_mode=json_mode)
    if _emit_coverage_env_skip(
        cfg,
        json_mode=json_mode,
        min_pct=resolved_min_pct,
        include_properties=include_properties,
        property_profile=property_profile,
    ):
        return
    task = task_coverage(
        min_pct=resolved_min_pct,
        include_properties=include_properties,
        property_profile=property_profile,
    )
    if task is None:
        return
    if json_mode:
        run_task_json(
            "coverage",
            task,
            {
                "min_pct": resolved_min_pct,
                "include_properties": include_properties,
                "property_profile": property_profile if include_properties else None,
            },
        )
        return
    run(task)


def _coverage_options(
    cfg: InterlockConfig,
    *,
    min_pct: int | None,
    include_properties: bool,
    property_profile: str,
) -> tuple[int, bool, str]:
    requested_profile = arg_flag_value("--properties", property_profile)
    if requested_profile is not None:
        include_properties = True
        property_profile = requested_profile
    return _coverage_min_pct(cfg, min_pct), include_properties, property_profile


def _validate_property_profile(property_profile: str, *, json_mode: bool) -> None:
    if property_profile in _PROPERTY_PROFILE_SET:
        return
    if json_mode:
        ui.print_json({
            "command": "coverage",
            "passed": False,
            "error": f"unsupported property profile {property_profile!r}",
            "expected_property_profiles": list(PROPERTY_PROFILES),
        })
        sys.exit(1)
    choices = "|".join(PROPERTY_PROFILES)
    fail_skip(f"coverage: unsupported property profile {property_profile!r} (expected {choices})")


def _emit_coverage_env_skip(
    cfg: InterlockConfig,
    *,
    json_mode: bool,
    min_pct: int,
    include_properties: bool,
    property_profile: str,
) -> bool:
    if not json_mode or project_env_ready(cfg):
        return False
    ui.print_json(
        _coverage_skip_payload(
            min_pct=min_pct,
            include_properties=include_properties,
            property_profile=property_profile,
            reason=project_env_skip_message("coverage"),
            next_action=(
                "Create or sync the project environment, then rerun `interlocks coverage`."
            ),
        )
    )
    return True


def _coverage_min_pct(cfg: InterlockConfig, min_pct: int | None) -> int:
    return min_pct if min_pct is not None else int(arg_value("--min=", str(cfg.coverage_min)))


def _coverage_skip_payload(
    *,
    min_pct: int,
    include_properties: bool,
    property_profile: str,
    reason: str,
    next_action: str,
) -> dict[str, object]:
    return {
        "command": "coverage",
        "passed": True,
        "status": "skipped",
        "min_pct": min_pct,
        "include_properties": include_properties,
        "property_profile": property_profile if include_properties else None,
        "reason": reason,
        "next_actions": [next_action],
    }
