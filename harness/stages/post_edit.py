"""Post-edit stage — format if source files have uncommitted changes (Claude Code hook)."""

from __future__ import annotations

from harness.git import changed_py_files
from harness.runner import run, tool


def cmd_post_edit() -> None:
    """Format if source files have uncommitted changes (Claude Code hook)."""
    files = changed_py_files()
    if not files:
        return
    run("Fix lint errors", tool("ruff", "check", "--fix", *files), no_exit=True, quiet=True)
    run("Format code", tool("ruff", "format", *files), no_exit=True, quiet=True)
