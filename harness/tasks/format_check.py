"""Format check — read-only ruff format --check."""

from __future__ import annotations

from harness.runner import run


def cmd_format_check() -> None:
    run("Format check", ["uv", "run", "ruff", "format", "--check", "."])
