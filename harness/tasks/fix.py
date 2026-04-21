"""Fix lint errors with ruff."""

from __future__ import annotations

from harness.runner import run


def cmd_fix(files: list[str] | None = None) -> None:
    target = files or ["."]
    run("Fix lint errors", ["uv", "run", "ruff", "check", "--fix", *target])
