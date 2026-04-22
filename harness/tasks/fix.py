"""Fix lint errors with ruff."""

from __future__ import annotations

from harness.runner import run, tool


def cmd_fix(files: list[str] | None = None, *, no_exit: bool = False) -> None:
    target = files or ["."]
    run("Fix lint errors", tool("ruff", "check", "--fix", *target), no_exit=no_exit)
