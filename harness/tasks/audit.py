"""Dependency audit via pip-audit."""

from __future__ import annotations

from harness.runner import run


def cmd_audit() -> None:
    run("Dep audit", ["uv", "run", "--with", "pip-audit", "pip-audit"])
