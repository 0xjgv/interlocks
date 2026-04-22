"""Tests under coverage with threshold + uncovered listing."""

from __future__ import annotations

from harness.detect import detect_test_runner
from harness.paths import TEST_DIR
from harness.runner import arg_value, python_m, run


def cmd_coverage(*, min_pct: int | None = None) -> None:
    """Run tests under coverage and report against ``min_pct`` (default: ``--min=N`` or 0)."""
    if min_pct is None:
        min_pct = int(arg_value("--min=", "0"))
    if detect_test_runner() == "pytest":
        cmd = python_m("coverage", "run", "-m", "pytest", TEST_DIR, "-q")
    else:
        cmd = python_m("coverage", "run", "-m", "unittest", "discover", "-s", TEST_DIR, "-q")
    run("Coverage (run)", cmd, test_summary=True)
    run(
        f"Coverage >= {min_pct}%",
        python_m("coverage", "report", "--show-missing", f"--fail-under={min_pct}"),
    )
