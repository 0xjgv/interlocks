"""Run tests."""

from __future__ import annotations

from harness.detect import detect_test_runner
from harness.paths import TEST_DIR
from harness.runner import python_m, run


def cmd_test() -> None:
    if detect_test_runner() == "pytest":
        run("Run tests", python_m("pytest", TEST_DIR, "-q"), test_summary=True)
    else:
        run(
            "Run tests",
            python_m("unittest", "discover", "-s", TEST_DIR, "-q"),
            test_summary=True,
        )
