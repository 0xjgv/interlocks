"""Type-check with basedpyright."""

from __future__ import annotations

from harness.paths import SRC_DIR
from harness.runner import Task, run, tool


def task_typecheck() -> Task:
    return Task("Type check", tool("basedpyright", SRC_DIR))


def cmd_typecheck() -> None:
    run(task_typecheck())
