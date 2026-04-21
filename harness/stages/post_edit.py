"""Post-edit stage — format if source files have uncommitted changes (Claude Code hook)."""

from __future__ import annotations

from harness.git import changed_py_files
from harness.runner import run


def cmd_post_edit() -> None:
    """Format if source files have uncommitted changes (Claude Code hook)."""
    if not changed_py_files():
        return
    run("Fix lint errors", ["uv", "run", "ruff", "check", "--fix", "."], no_exit=True)
    run("Format code", ["uv", "run", "ruff", "format", "."], no_exit=True)
