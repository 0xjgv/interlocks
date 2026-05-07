"""Lint code with ruff (read-only)."""

from __future__ import annotations

from interlocks.runner import Task, run
from interlocks.tasks._ruff import make_ruff_task


def task_lint(files: list[str] | None = None) -> Task:
    return make_ruff_task("lint", files)


def cmd_lint(files: list[str] | None = None) -> None:
    run(task_lint(files))
