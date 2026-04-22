"""Lint code with ruff (read-only)."""

from __future__ import annotations

from harness.runner import run, tool


def cmd_lint(files: list[str] | None = None) -> None:
    target = files or ["."]
    run("Lint check", tool("ruff", "check", *target))
