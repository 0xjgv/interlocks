"""Format check — read-only ruff format --check."""

from __future__ import annotations

from harness.runner import run, tool


def cmd_format_check() -> None:
    run("Format check", tool("ruff", "format", "--check", "."))
