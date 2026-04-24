"""Post-edit stage — format if source files have uncommitted changes (Claude Code hook)."""

from __future__ import annotations

from harness import ui
from harness.git import changed_py_files
from harness.runner import Task, run, tool


def cmd_post_edit() -> None:
    files = changed_py_files()
    if not files:
        return
    ui.section("Post-edit")
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
