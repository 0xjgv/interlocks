"""Architecture checks via import-linter."""

from __future__ import annotations

from pathlib import Path

from harness.runner import run, warn_skip


def cmd_arch() -> None:
    """Run import-linter against .importlinter."""
    if not Path(".importlinter").exists():
        warn_skip("Arch: no .importlinter — skipped")
        return
    run("Arch (import-linter)", ["uv", "run", "lint-imports"])
