"""Post-edit stage — format if source files have uncommitted changes (Claude Code hook)."""

from __future__ import annotations

import time

from interlocks import ui
from interlocks.config import load_config
from interlocks.git import changed_py_files
from interlocks.runner import Task, run, tool

_RUFF_STEPS = (
    ("Fix lint errors", "fix", ("check", "--fix")),
    ("Format code", "format", ("format",)),
)


def cmd_post_edit() -> None:
    files = changed_py_files()
    if not files:
        return
    start = time.monotonic()
    ui.banner(load_config())
    ui.section("Post-edit")
    try:
        for description, label, args in _RUFF_STEPS:
            run(
                Task(
                    description,
                    tool("ruff", *args, *files),
                    label=label,
                    display=f"ruff {' '.join(args)}",
                ),
                no_exit=True,
            )
    finally:
        ui.stage_footer(time.monotonic() - start)
