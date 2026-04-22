"""Dependency audit via pip-audit."""

from __future__ import annotations

from harness.runner import python_m, run


def cmd_audit() -> None:
    run("Dep audit", python_m("pip_audit"))
