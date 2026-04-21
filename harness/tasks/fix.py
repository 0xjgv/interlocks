"""Fix lint errors with ruff."""

from __future__ import annotations

from harness.runner import run


def cmd_fix(files: list[str] | None = None, *, no_exit: bool = False) -> None:
    target = files or ["."]
    run("Fix lint errors", ["uv", "run", "ruff", "check", "--fix", *target], no_exit=no_exit)
