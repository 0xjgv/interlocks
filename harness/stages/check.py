"""Check stage."""

from __future__ import annotations

from harness.reports.suppressions import print_suppressions_report
from harness.runner import run, run_tasks, section
from harness.tasks.deps import task_deps
from harness.tasks.fix import cmd_fix
from harness.tasks.format import cmd_format
from harness.tasks.test import task_test
from harness.tasks.typecheck import task_typecheck


def cmd_check() -> None:
    """Fix, format (serial — both mutate files), then typecheck + test in parallel.

    ``deps`` runs advisory at the end: fast feedback on dep hygiene without
    halting the edit loop on deptry noise. CI is where it gates.
    """
    section("Quality Checks")
    try:
        cmd_fix()
        cmd_format()
        run_tasks([task_typecheck(), task_test()])
        run(task_deps(), no_exit=True)
    finally:
        print_suppressions_report()
