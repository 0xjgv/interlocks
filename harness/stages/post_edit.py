"""Post-edit stage — format if source files have uncommitted changes (Claude Code hook)."""

from __future__ import annotations

from harness.git import changed_py_files
from harness.runner import Task, run, section, tool


def cmd_post_edit() -> None:
    files = changed_py_files()
    if not files:
        return
    section("Post-edit")
    run(Task("Fix lint errors", tool("ruff", "check", "--fix", *files)), no_exit=True)
    run(Task("Format code", tool("ruff", "format", *files)), no_exit=True)
