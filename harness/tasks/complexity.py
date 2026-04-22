"""Complexity gate via lizard. Called by stages/ci; not exposed in TASKS."""

from __future__ import annotations

from harness.paths import SRC_DIR, TEST_DIR
from harness.runner import Task, run, tool


def task_complexity() -> Task:
    return Task(
        "Complexity (lizard)",
        tool("lizard", SRC_DIR, TEST_DIR, "-C", "15", "-a", "7", "-L", "100", "-i", "0"),
    )


def cmd_complexity() -> None:
    run(task_complexity())
