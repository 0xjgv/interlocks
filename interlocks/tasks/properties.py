"""Property tests via pytest + Hypothesis profiles."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from interlocks import ui
from interlocks.config import (
    InterlockConfig,
    load_config,
    project_env_ready,
    project_env_skip_message,
    python_command_prefix,
)
from interlocks.defaults_path import path as defaults_path
from interlocks.hypothesis_profiles import PROPERTY_PROFILES, hypothesis_profile_setup_source
from interlocks.runner import (
    Task,
    arg_value,
    fail_skip,
    run,
    run_task_json,
    section,
    warn_skip,
)
from interlocks.scaffold import (
    ScaffoldFile,
    ensure_bytes_file,
    next_actions_without_declared_dependency,
    scaffold_file,
)

if TYPE_CHECKING:
    from pathlib import Path

_PROPERTY_PROFILE_SET = frozenset(PROPERTY_PROFILES)
_SCAFFOLD_EXAMPLE = "test_example_properties.py"
_INIT_PROPERTIES_DEP_ACTION = "Add `hypothesis>=6` to test/dev dependencies if it is missing."
_INIT_PROPERTIES_NEXT_ACTIONS = (
    _INIT_PROPERTIES_DEP_ACTION,
    "Create or sync the project environment if `interlocks doctor` reports one missing.",
    "Replace the example property with domain invariants.",
    "Run `interlocks gate properties --profile=check`.",
)
_INIT_PROPERTIES_DOMAIN_FILE_LIMIT = 20


@dataclass(frozen=True)
class _InitPropertiesResult:
    status: str
    files: tuple[ScaffoldFile, ...] = ()
    domain_files: tuple[Path, ...] = ()
    next_actions: tuple[str, ...] = field(default_factory=tuple)


def property_test_files(cfg: InterlockConfig) -> list[Path]:
    """Return property test files under the configured property-test directory."""
    root = cfg.properties_dir
    if root is None or not root.is_dir():
        return []
    files = [*root.rglob("test_*.py"), *root.rglob("*_test.py")]
    return sorted(set(files))


def domain_property_test_files(cfg: InterlockConfig) -> list[Path]:
    """Return property tests excluding the unchanged scaffold example."""
    return [path for path in property_test_files(cfg) if not _is_scaffold_example(path)]


def _is_scaffold_example(path: Path) -> bool:
    if path.name != _SCAFFOLD_EXAMPLE:
        return False
    try:
        return path.read_bytes() == defaults_path("properties_test_example.py").read_bytes()
    except OSError:
        return False


def _properties_dir_arg(cfg: InterlockConfig) -> str:
    if cfg.properties_dir is None:
        return "properties"
    return cfg.relpath(cfg.properties_dir)


def _hypothesis_import_check_cmd(cfg: InterlockConfig) -> list[str]:
    message = (
        "interlocks: Hypothesis is not importable in the target Python environment. "
        "Add `hypothesis` to the project's test/dev dependencies, then re-run "
        "`interlocks gate properties`.\n"
    )
    code = (
        "import importlib.util, sys; "
        "ok = importlib.util.find_spec('hypothesis') is not None; "
        f"sys.stderr.write({message!r}) if not ok else None; "
        "raise SystemExit(0 if ok else 1)"
    )
    return [*python_command_prefix(cfg), "-c", code]


def _pytest_with_profiles_cmd(
    cfg: InterlockConfig, properties_dir: str, profile: str
) -> list[str]:
    code = (
        hypothesis_profile_setup_source() + "\nimport pytest, sys; "
        "raise SystemExit(pytest.main(sys.argv[1:]))"
    )
    return [
        *python_command_prefix(cfg),
        "-c",
        code,
        properties_dir,
        "-q",
        f"--hypothesis-profile={profile}",
        *cfg.pytest_args,
    ]


def task_properties(*, profile: str = "ci") -> Task | None:
    """Build the property-test task, or return ``None`` when no properties exist."""
    cfg = load_config()
    files = property_test_files(cfg)
    if not files:
        return None
    properties_dir = _properties_dir_arg(cfg)
    return Task(
        "Property tests",
        _pytest_with_profiles_cmd(cfg, properties_dir, profile),
        pre_cmds=(_hypothesis_import_check_cmd(cfg),),
        test_summary=True,
        label="properties",
        display=f"pytest {properties_dir} --hypothesis-profile={profile}",
        start_status="running",
    )


def cmd_properties(*, profile_default: str = "ci") -> None:
    cfg = load_config()
    profile = arg_value("--profile=", profile_default)
    if profile not in _PROPERTY_PROFILE_SET:
        choices = "|".join(PROPERTY_PROFILES)
        if ui.is_json():
            ui.print_json({
                "command": "properties",
                "passed": False,
                "error": f"unsupported profile {profile!r}",
                "expected_profiles": list(PROPERTY_PROFILES),
            })
            sys.exit(1)
        fail_skip(f"properties: unsupported profile {profile!r} (expected {choices})")
    task = task_properties(profile=profile)
    if task is None:
        properties_dir = _properties_dir_arg(cfg)
        if ui.is_json():
            ui.print_json(
                _properties_skip_payload(
                    cfg,
                    profile,
                    "no property tests detected",
                    f"Run `interlocks init --properties` to scaffold {properties_dir}/.",
                )
            )
            return
        warn_skip(
            "properties: no property tests detected — run `interlocks init --properties` "
            f"to scaffold {properties_dir}/"
        )
        return
    if not project_env_ready(cfg):
        if ui.is_json():
            ui.print_json(
                _properties_skip_payload(
                    cfg,
                    profile,
                    project_env_skip_message("properties"),
                    "Create or sync the project environment, then rerun "
                    "`interlocks gate properties`.",
                )
            )
            return
        warn_skip(project_env_skip_message("properties"))
        return
    if ui.is_json():
        run_task_json(
            "properties",
            task,
            {"profile": profile, "properties_dir": _properties_dir_arg(cfg)},
        )
        return
    run(task)


def _properties_skip_payload(
    cfg: InterlockConfig,
    profile: str,
    reason: str,
    next_action: str,
) -> dict[str, object]:
    return {
        "command": "properties",
        "passed": True,
        "status": "skipped",
        "profile": profile,
        "properties_dir": _properties_dir_arg(cfg),
        "reason": reason,
        "next_actions": [next_action],
    }


def cmd_init_properties() -> None:
    section("Init properties")
    cfg = load_config()
    properties_dir = cfg.properties_dir or (cfg.project_root / "properties")
    domain_files = domain_property_test_files(cfg)
    if domain_files:
        if ui.is_json():
            ui.print_json(
                _init_properties_payload(
                    cfg,
                    properties_dir,
                    _InitPropertiesResult(
                        status="domain-properties-present",
                        domain_files=tuple(domain_files),
                        next_actions=("Run `interlocks gate properties --profile=check`.",),
                    ),
                )
            )
            return
        print(f"kept {cfg.relpath(properties_dir)}/")
        print("next: run `interlocks gate properties --profile=check`")
        return
    files: list[ScaffoldFile] = []
    for target, template in _init_properties_targets(properties_dir):
        files.append(
            scaffold_file(
                cfg.relpath(target),
                ensure_bytes_file(target, defaults_path(template).read_bytes()),
            )
        )
    if ui.is_json():
        ui.print_json(
            _init_properties_payload(
                cfg,
                properties_dir,
                _InitPropertiesResult(
                    status="scaffold-present",
                    files=tuple(files),
                    next_actions=_init_properties_next_actions(cfg),
                ),
            )
        )
        return
    for file in files:
        action = file["action"]
        path = file["path"]
        print(f"{action} {path}")
    _print_init_properties_next_steps(cfg)


def _init_properties_payload(
    cfg: InterlockConfig,
    properties_dir: Path,
    result: _InitPropertiesResult,
) -> dict[str, object]:
    domain_paths = [cfg.relpath(path) for path in result.domain_files]
    payload: dict[str, object] = {
        "command": "init",
        "passed": True,
        "status": result.status,
        "properties_dir": cfg.relpath(properties_dir),
        "files": list(result.files),
        "domain_property_test_count": len(domain_paths),
        "domain_property_tests": domain_paths[:_INIT_PROPERTIES_DOMAIN_FILE_LIMIT],
        "next_actions": list(result.next_actions),
    }
    omitted = len(domain_paths) - _INIT_PROPERTIES_DOMAIN_FILE_LIMIT
    if omitted > 0:
        payload["omitted_domain_property_tests"] = omitted
    return payload


def _init_properties_targets(properties_dir: Path) -> tuple[tuple[Path, str], ...]:
    return ((properties_dir / "test_example_properties.py", "properties_test_example.py"),)


def _init_properties_next_actions(cfg: InterlockConfig) -> tuple[str, ...]:
    return next_actions_without_declared_dependency(
        cfg.pyproject,
        dependency="hypothesis",
        dependency_action=_INIT_PROPERTIES_DEP_ACTION,
        actions=_INIT_PROPERTIES_NEXT_ACTIONS,
    )


def _print_init_properties_next_steps(cfg: InterlockConfig) -> None:
    ui.print_next_actions(_init_properties_next_actions(cfg))
