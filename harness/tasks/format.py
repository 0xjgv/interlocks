"""Format code with ruff."""

from __future__ import annotations

from harness.runner import run


def cmd_format(files: list[str] | None = None) -> None:
    target = files or ["."]
    run("Format code", ["uv", "run", "ruff", "format", *target])
