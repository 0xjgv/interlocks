"""Format code with ruff."""

from __future__ import annotations

from harness.runner import Task, run, tool


def task_format(files: list[str] | None = None) -> Task:
    target = files or ["."]
    return Task("Format code", tool("ruff", "format", *target))


def cmd_format(files: list[str] | None = None, *, no_exit: bool = False) -> None:
    run(task_format(files), no_exit=no_exit)
