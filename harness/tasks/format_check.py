"""Format check — read-only ruff format --check."""

from __future__ import annotations

from harness.runner import Task, run, tool


def task_format_check() -> Task:
    return Task("Format check", tool("ruff", "format", "--check", "."))


def cmd_format_check() -> None:
    run(task_format_check())
