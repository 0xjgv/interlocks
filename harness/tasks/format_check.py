"""Format check — read-only ruff format --check."""

from __future__ import annotations

from harness.runner import Task, run, tool
from harness.tasks._ruff import ruff_config_args


def task_format_check() -> Task:
    return Task("Format check", tool("ruff", "format", "--check", *ruff_config_args(), "."))


def cmd_format_check() -> None:
    run(task_format_check())
