"""Tests under coverage with threshold + uncovered listing."""

from __future__ import annotations

from harness.detect import detect_test_runner
from harness.paths import TEST_DIR
from harness.runner import Task, arg_value, python_m, run


def task_coverage(*, min_pct: int | None = None) -> Task:
    """Run tests under coverage and report against ``min_pct`` (default: ``--min=N`` or 0)."""
    if min_pct is None:
        min_pct = int(arg_value("--min=", "0"))
    if detect_test_runner() == "pytest":
        run_cmd = python_m("coverage", "run", "-m", "pytest", TEST_DIR, "-q")
    else:
        run_cmd = python_m("coverage", "run", "-m", "unittest", "discover", "-s", TEST_DIR, "-q")
    return Task(
        f"Coverage >= {min_pct}%",
        python_m("coverage", "report", "--show-missing", f"--fail-under={min_pct}"),
        pre_cmds=(run_cmd,),
        test_summary=True,
    )


def cmd_coverage(*, min_pct: int | None = None) -> None:
    run(task_coverage(min_pct=min_pct))
