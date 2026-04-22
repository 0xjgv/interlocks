"""CI stage."""

from __future__ import annotations

from harness.config import load_config
from harness.runner import run_tasks, section
from harness.tasks.acceptance import task_acceptance
from harness.tasks.arch import task_arch
from harness.tasks.complexity import task_complexity
from harness.tasks.coverage import task_coverage
from harness.tasks.crap import cmd_crap
from harness.tasks.deps import task_deps
from harness.tasks.format_check import task_format_check
from harness.tasks.lint import task_lint
from harness.tasks.mutation import cmd_mutation
from harness.tasks.typecheck import task_typecheck


def cmd_ci() -> None:
    """Full verification: format_check, lint, complexity, deps, arch, typecheck, coverage,
    CRAP, (optionally) mutation."""
    section("CI Checks")
    tasks = [
        task_format_check(),
        task_lint(),
        task_complexity(),
        task_deps(),
        task_typecheck(),
        task_coverage(),
    ]
    for optional in (task_arch(), task_acceptance()):
        if optional is not None:
            tasks.append(optional)
    run_tasks(tasks)
    # CRAP/mutation read coverage.xml produced by task_coverage — keep sequential.
    cmd_crap()
    if load_config().run_mutation_in_ci:
        cmd_mutation()
