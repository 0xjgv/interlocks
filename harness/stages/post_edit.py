"""Post-edit stage — format if source files have uncommitted changes (Claude Code hook)."""

from __future__ import annotations

import time

from harness import ui
from harness.config import load_config
from harness.git import changed_py_files
from harness.runner import Task, run, tool


def cmd_post_edit() -> None:
    files = changed_py_files()
    if not files:
        return
    start = time.monotonic()
    ui.banner(load_config())
    ui.section("Post-edit")
    try:
        run(
            Task(
                "Fix lint errors",
                tool("ruff", "check", "--fix", *files),
                label="fix",
                display="ruff check --fix",
            ),
            no_exit=True,
        )
        run(
            Task(
                "Format code",
                tool("ruff", "format", *files),
                label="format",
                display="ruff format",
            ),
            no_exit=True,
        )
    finally:
        ui.stage_footer(time.monotonic() - start)
