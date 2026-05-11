"""Pre-commit stage — staged checks + tests if source files staged."""

from __future__ import annotations

import time

from interlocks import ui
from interlocks.config import load_config
from interlocks.git import stage, staged_py_files
from interlocks.runner import print_stage_verdict, reset_results, run_tasks
from interlocks.skip import current_skip_policy, maybe_print_skip_banner, run_unless_skipped
from interlocks.tasks.fix import cmd_fix
from interlocks.tasks.format import cmd_format
from interlocks.tasks.test import task_test
from interlocks.tasks.typecheck import task_typecheck


def cmd_pre_commit() -> None:
    """Staged checks + tests if source files staged."""
    files = staged_py_files()
    if not files:
        print("pre-commit: skipped — no staged python files")
        return

    start = time.monotonic()
    cfg = load_config()
    reset_results()
    skip_policy = current_skip_policy()
    ui.banner(cfg)
    maybe_print_skip_banner(skip_policy)
    ui.section("Pre-commit Checks")
    try:
        run_unless_skipped("fix", lambda: cmd_fix(files), skip_policy)
        run_unless_skipped("format", lambda: cmd_format(files), skip_policy)
        if not (skip_policy.enabled("fix") and skip_policy.enabled("format")):
            stage(files)

        src_prefix = f"{cfg.src_dir_arg}/"
        tasks = [task_typecheck()]
        if any(f.startswith(src_prefix) for f in files):
            test_task = task_test()
            if test_task is not None:
                tasks.append(test_task)
        run_tasks(tasks)
    finally:
        elapsed = time.monotonic() - start
        ui.stage_footer(elapsed)
        print_stage_verdict("pre-commit", elapsed)
