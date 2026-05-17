"""Post-edit stage — format if source files have uncommitted changes (Claude Code hook)."""

from __future__ import annotations

import time

from interlocks import ui
from interlocks.config import load_config
from interlocks.git import changed_py_files
from interlocks.stages._budgeted import run_budgeted_mutation


def cmd_post_edit() -> None:
    files = changed_py_files()
    if not files:
        return
    start = time.monotonic()
    cfg = load_config()
    ui.banner(cfg)
    ui.section("Post-edit")
    try:
        run_budgeted_mutation(base="HEAD", emit_legacy_rows=False)
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(f"post-edit: budgeted mutation skipped advisory ({exc.code})")
    finally:
        ui.stage_footer(time.monotonic() - start)
