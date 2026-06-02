"""Post-edit stage — format if source files have uncommitted changes (Claude Code hook)."""

from __future__ import annotations

import time

from interlocks import ui
from interlocks.config import load_config
from interlocks.git import changed_py_files
from interlocks.runner import record_result, record_skip, reset_results, stage_json
from interlocks.skip import current_skip_policy, maybe_print_skip_banner
from interlocks.stages._budgeted import run_budgeted_mutation


def cmd_post_edit() -> None:
    start = time.monotonic()
    reset_results()
    files = changed_py_files()
    if not files:
        if ui.is_json():
            record_skip("post-edit", "no uncommitted Python files")
            ui.print_json(stage_json("post-edit", passed=True, elapsed=time.monotonic() - start))
        return
    cfg = load_config()
    skip_policy = current_skip_policy()
    ui.banner(cfg)
    maybe_print_skip_banner(skip_policy)
    ui.section("Post-edit")
    try:
        run_budgeted_mutation(base="HEAD", emit_legacy_rows=False, skip_policy=skip_policy)
    except SystemExit as exc:
        if exc.code not in (0, None):
            record_result(
                "fix optimize",
                status="warn",
                elapsed=None,
                detail=f"budgeted mutation exited {exc.code}",
            )
            if not ui.is_json():
                print(f"post-edit: budgeted mutation skipped advisory ({exc.code})")
    else:
        if not (skip_policy.enabled("fix") or skip_policy.enabled("format")):
            record_result("fix optimize", status="ok", elapsed=None, detail=None)
    finally:
        elapsed = time.monotonic() - start
        ui.stage_footer(elapsed)
        if ui.is_json():
            ui.print_json(stage_json("post-edit", passed=True, elapsed=elapsed))
