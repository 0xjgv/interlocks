"""Pre-commit stage — staged checks + tests if source files staged."""

from __future__ import annotations

from harness.config import load_config
from harness.git import stage, staged_py_files
from harness.runner import run_tasks, section
from harness.tasks.fix import cmd_fix
from harness.tasks.format import cmd_format
from harness.tasks.test import task_test
from harness.tasks.typecheck import task_typecheck


def cmd_pre_commit() -> None:
    """Staged checks + tests if source files staged."""
    files = staged_py_files()
    if not files:
        print("No staged Python files — skipping checks")
        return

    section("Pre-commit Checks")
    cmd_fix(files)
    cmd_format(files)
    stage(files)

    cfg = load_config()
    src_prefix = f"{cfg.src_dir_arg}/"
    tasks = [task_typecheck()]
    if any(f.startswith(src_prefix) for f in files):
        test_task = task_test()
        if test_task is not None:
            tasks.append(test_task)
    run_tasks(tasks)
