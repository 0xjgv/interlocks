"""Post-edit stage — format if source files have uncommitted changes (Claude Code hook)."""

from __future__ import annotations

import time

from interlocks import ui
from interlocks.config import load_config
from interlocks.git import changed_py_files
from interlocks.runner import Task, run, uvx_tool

_RUFF_STEPS = (
    ("Fix lint errors", "fix", ("check", "--fix")),
    ("Format code", "format", ("format",)),
)


def cmd_post_edit() -> None:
    files = changed_py_files()
    if not files:
        return
    start = time.monotonic()
    cfg = load_config()
    ui.banner(cfg)
    ui.section("Post-edit")
    ruff_version = cfg.tool_version("ruff")
    try:
        for description, label, args in _RUFF_STEPS:
            run(
                Task(
                    description,
                    uvx_tool("ruff", *args, *files, version=ruff_version),
                    label=label,
                    display=f"ruff {' '.join(args)}",
                ),
                no_exit=True,
            )
    finally:
        ui.stage_footer(time.monotonic() - start)
