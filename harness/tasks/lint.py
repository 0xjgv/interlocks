"""Lint code with ruff (read-only)."""

from __future__ import annotations

from harness.runner import Task, run, tool
from harness.tasks._ruff import ruff_config_args


def task_lint(files: list[str] | None = None) -> Task:
    target = files or ["."]
    return Task(
        "Lint check",
        tool("ruff", "check", *ruff_config_args(), *target),
        label="lint",
        display="ruff check",
    )


def cmd_lint(files: list[str] | None = None) -> None:
    run(task_lint(files))
