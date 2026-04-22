"""Run tests."""

from __future__ import annotations

from harness.detect import detect_test_runner
from harness.paths import TEST_DIR
from harness.runner import Task, python_m, run


def task_test() -> Task:
    if detect_test_runner() == "pytest":
        return Task("Run tests", python_m("pytest", TEST_DIR, "-q"), test_summary=True)
    return Task(
        "Run tests",
        python_m("unittest", "discover", "-s", TEST_DIR, "-q"),
        test_summary=True,
    )


def cmd_test() -> None:
    run(task_test())
