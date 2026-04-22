"""Tests under coverage with threshold + uncovered listing."""

from __future__ import annotations

from harness.config import build_coverage_test_command, invoker_prefix, load_config
from harness.defaults_path import has_project_config, path
from harness.runner import Task, arg_value, run


def _coverage_rcfile_args() -> list[str]:
    """``--rcfile=<bundled>`` when the project owns no coverage config, else ``[]``.

    The ``=`` form is required so ``uv run`` doesn't mistake ``--rcfile`` for one of
    its own options before passing it through to coverage.
    """
    cfg = load_config()
    if has_project_config(cfg, "coverage", sidecars=(".coveragerc",)):
        return []
    return [f"--rcfile={path('coveragerc')}"]


def task_coverage(*, min_pct: int | None = None) -> Task:
    """Run tests under coverage and report against ``min_pct``.

    Precedence: explicit argument > ``--min=N`` on argv > ``cfg.coverage_min``.
    """
    cfg = load_config()
    if min_pct is None:
        min_pct = int(arg_value("--min=", str(cfg.coverage_min)))
    rcfile_args = _coverage_rcfile_args()
    run_cmd = build_coverage_test_command(cfg)
    if rcfile_args:
        run_cmd[run_cmd.index("run") + 1 : run_cmd.index("run") + 1] = rcfile_args
    report_cmd = [
        *invoker_prefix(cfg),
        "coverage",
        "report",
        *rcfile_args,
        "--show-missing",
        f"--fail-under={min_pct}",
    ]
    return Task(
        f"Coverage >= {min_pct}%",
        report_cmd,
        pre_cmds=(run_cmd,),
        test_summary=True,
    )


def cmd_coverage(*, min_pct: int | None = None) -> None:
    run(task_coverage(min_pct=min_pct))
