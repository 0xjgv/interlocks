"""Tests under coverage with threshold + uncovered listing."""

from __future__ import annotations

from harness.paths import TEST_DIR
from harness.runner import arg_value, run


def cmd_coverage(*, min_pct: int | None = None) -> None:
    """Run tests under coverage and report against ``min_pct`` (default: ``--min=N`` or 0)."""
    if min_pct is None:
        min_pct = int(arg_value("--min=", "0"))
    run(
        "Coverage (run)",
        ["uv", "run", "coverage", "run", "-m", "unittest", "discover", "-s", TEST_DIR, "-q"],
    )
    run(
        f"Coverage >= {min_pct}%",
        ["uv", "run", "coverage", "report", "--show-missing", f"--fail-under={min_pct}"],
    )
