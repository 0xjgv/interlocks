"""Format check — read-only ruff format --check."""

from __future__ import annotations

from interlocks import ui
from interlocks.runner import Task, run, run_task_json
from interlocks.tasks._ruff import make_ruff_task


def task_format_check() -> Task:
    return make_ruff_task("format-check")


def cmd_format_check() -> None:
    if ui.is_json():
        run_task_json("format-check", task_format_check())
        return
    run(task_format_check())
