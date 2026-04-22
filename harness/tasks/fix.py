"""Fix lint errors with ruff."""

from __future__ import annotations

from harness.runner import Task, run, tool


def task_fix(files: list[str] | None = None) -> Task:
    target = files or ["."]
    return Task("Fix lint errors", tool("ruff", "check", "--fix", *target))


def cmd_fix(files: list[str] | None = None, *, no_exit: bool = False) -> None:
    run(task_fix(files), no_exit=no_exit)
