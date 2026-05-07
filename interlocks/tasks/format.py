"""Format code with ruff."""

from __future__ import annotations

from interlocks.runner import Task, run
from interlocks.tasks._ruff import make_ruff_task


def task_format(files: list[str] | None = None) -> Task:
    return make_ruff_task("format", files)


def cmd_format(files: list[str] | None = None, *, no_exit: bool = False) -> None:
    run(task_format(files), no_exit=no_exit)
