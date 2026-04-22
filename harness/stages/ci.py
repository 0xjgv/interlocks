"""CI stage."""

from __future__ import annotations

from harness.runner import run_tasks, section
from harness.tasks.arch import task_arch
from harness.tasks.complexity import task_complexity
from harness.tasks.coverage import task_coverage
from harness.tasks.deps import task_deps
from harness.tasks.format_check import task_format_check
from harness.tasks.lint import task_lint
from harness.tasks.typecheck import task_typecheck


def cmd_ci() -> None:
    """Full verification: format_check, lint, complexity, deps, arch, typecheck, coverage."""
    section("CI Checks")
    tasks = [
        task_format_check(),
        task_lint(),
        task_complexity(),
        task_deps(),
        task_typecheck(),
        task_coverage(),
    ]
    arch = task_arch()
    if arch is not None:
        tasks.append(arch)
    run_tasks(tasks)
