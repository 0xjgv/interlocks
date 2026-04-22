"""Dependency audit via pip-audit."""

from __future__ import annotations

from harness.runner import Task, python_m, run


def task_audit() -> Task:
    return Task("Dep audit", python_m("pip_audit"))


def cmd_audit() -> None:
    run(task_audit())
