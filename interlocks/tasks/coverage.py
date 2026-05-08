"""Tests under coverage with threshold + uncovered listing."""

from __future__ import annotations

from interlocks.config import (
    InterlockConfig,
    build_coverage_test_command,
    coverage_invoker_prefix,
    load_config,
    python_command_prefix,
)
from interlocks.defaults_path import has_project_config, path
from interlocks.runner import Task, arg_value, run


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


def task_coverage(*, min_pct: int | None = None) -> Task:
    """Run tests under coverage and report against ``min_pct``.

    Precedence: explicit argument > ``--min=N`` on argv > ``cfg.coverage_min``.
    """
    cfg = load_config()
    if min_pct is None:
        min_pct = int(arg_value("--min=", str(cfg.coverage_min)))
    rcfile_args = _coverage_rcfile_args(cfg)
    run_cmd = build_coverage_test_command(cfg, coverage_args=tuple(rcfile_args))
    report_cmd = [
        *coverage_invoker_prefix(cfg),
        "coverage",
        "report",
        *rcfile_args,
        "--show-missing",
        f"--fail-under={min_pct}",
    ]
    pre_cmds = tuple(cmd for cmd in (_coverage_import_check_cmd(cfg), run_cmd) if cmd is not None)
    return Task(
        f"Coverage >= {min_pct}%",
        report_cmd,
        pre_cmds=pre_cmds,
        test_summary=True,
        label="coverage",
        display=f"coverage report --fail-under={min_pct}",
    )


def cmd_coverage(*, min_pct: int | None = None) -> None:
    run(task_coverage(min_pct=min_pct))
