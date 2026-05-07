"""Format check — read-only ruff format --check."""

from __future__ import annotations

from interlocks.runner import Task, run
from interlocks.tasks._ruff import make_ruff_task


def task_format_check() -> Task:
    return make_ruff_task("format-check")


def cmd_format_check() -> None:
    run(task_format_check())
