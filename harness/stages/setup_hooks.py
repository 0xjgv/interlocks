"""Install git pre-commit hook."""

from __future__ import annotations

from pathlib import Path


def cmd_hooks() -> None:
    """Install git pre-commit hook."""
    hook = Path(".git/hooks/pre-commit")
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\nuv run harness pre-commit\n", encoding="utf-8")
    hook.chmod(0o755)
    print("Installed pre-commit hook")
