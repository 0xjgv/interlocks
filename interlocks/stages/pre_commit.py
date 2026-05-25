"""Pre-commit stage — staged checks + tests if source files staged."""

from __future__ import annotations

import time

from interlocks import ui
from interlocks.config import load_config
from interlocks.git import stage, staged_py_files
from interlocks.runner import (
    Task,
    print_stage_verdict,
    record_skip,
    reset_results,
    results_snapshot,
    run_tasks,
    stage_json,
)
from interlocks.skip import SkipPolicy, current_skip_policy, maybe_print_skip_banner
from interlocks.stages._budgeted import run_budgeted_mutation
from interlocks.tasks.test import task_test
from interlocks.tasks.typecheck import task_typecheck


def cmd_pre_commit() -> None:
    """Staged checks + tests if source files staged."""
    start = time.monotonic()
    reset_results()
    files = staged_py_files()
    if not files:
        if ui.is_json():
            record_skip("pre-commit", "no staged Python files")
            ui.print_json(stage_json("pre-commit", passed=True, elapsed=time.monotonic() - start))
            return
        print("pre-commit: skipped — no staged python files")
        return

    cfg = load_config()
    skip_policy = current_skip_policy()
    ui.banner(cfg)
    maybe_print_skip_banner(skip_policy)
    ui.section("Pre-commit Checks")
    try:
        _run_pre_commit_checks(files, cfg.src_dir_arg, skip_policy)
    finally:
        elapsed = time.monotonic() - start
        _print_footer(elapsed)


def _run_pre_commit_checks(files: list[str], src_dir_arg: str, skip_policy: SkipPolicy) -> None:
    _run_budgeted_mutation(skip_policy)
    if not (skip_policy.enabled("fix") or skip_policy.enabled("format")):
        stage(files)

    src_prefix = f"{src_dir_arg}/"
    candidates: list[Task | None] = [task_typecheck()]
    if any(f.startswith(src_prefix) for f in files):
        candidates.append(task_test())
    run_tasks([t for t in candidates if t is not None])


def _run_budgeted_mutation(skip_policy: SkipPolicy) -> None:
    run_budgeted_mutation(base="HEAD", emit_legacy_rows=True, skip_policy=skip_policy)


def _print_footer(elapsed: float) -> None:
    ui.stage_footer(elapsed)
    print_stage_verdict("pre-commit", elapsed)
    if ui.is_json():
        passed = all(result.status == "ok" for result in results_snapshot())
        ui.print_json(stage_json("pre-commit", passed=passed, elapsed=elapsed))
