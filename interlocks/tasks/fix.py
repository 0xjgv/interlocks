"""Fix lint errors with ruff."""

from __future__ import annotations

from interlocks import ui
from interlocks.runner import Task, run, run_task_json
from interlocks.tasks._ruff import make_ruff_task


def task_fix(files: list[str] | None = None) -> Task:
    return make_ruff_task("fix", files)


def cmd_fix(files: list[str] | None = None, *, no_exit: bool = False) -> None:
    task = task_fix(files)
    if ui.is_json() and not no_exit:
        run_task_json("fix", task)
        return
    run(task, no_exit=no_exit)
