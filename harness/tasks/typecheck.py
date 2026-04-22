"""Type-check with basedpyright."""

from __future__ import annotations

from harness.paths import SRC_DIR
from harness.runner import run, tool


def cmd_typecheck() -> None:
    run("Type check", tool("basedpyright", SRC_DIR))
