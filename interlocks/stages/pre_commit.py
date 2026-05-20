"""Pre-commit stage — staged checks + tests if source files staged."""

from __future__ import annotations

import time

from interlocks import ui
from interlocks.config import load_config
from interlocks.git import stage, staged_py_files
from interlocks.runner import (
    Task,
    print_stage_verdict,
    reset_results,
    run_tasks,
)
from interlocks.skip import current_skip_policy, maybe_print_skip_banner, run_unless_skipped
from interlocks.stages._budgeted import run_budgeted_mutation
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
        run_unless_skipped("format", lambda: None, skip_policy)
        run_unless_skipped("fix", _run_budgeted_mutation, skip_policy)
        if not skip_policy.enabled("fix"):
            stage(files)

        src_prefix = f"{cfg.src_dir_arg}/"
        candidates: list[Task | None] = [task_typecheck()]
        if any(f.startswith(src_prefix) for f in files):
            candidates.append(task_test())
        run_tasks([t for t in candidates if t is not None])
    finally:
        elapsed = time.monotonic() - start
        ui.stage_footer(elapsed)
        print_stage_verdict("pre-commit", elapsed)


def _run_budgeted_mutation() -> None:
    run_budgeted_mutation(base="HEAD", emit_legacy_rows=True)
