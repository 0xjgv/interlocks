"""Check stage — fix, format, then {typecheck, test} in parallel; suppressions in finally."""

from __future__ import annotations

from harness.reports.suppressions import print_suppressions_report
from harness.runner import run_tasks, section
from harness.tasks.fix import cmd_fix
from harness.tasks.format import cmd_format
from harness.tasks.test import task_test
from harness.tasks.typecheck import task_typecheck


def cmd_check() -> None:
    """Fix, format (serial — both mutate files), then typecheck + test in parallel."""
    section("Quality Checks")
    try:
        cmd_fix()
        cmd_format()
        run_tasks([task_typecheck(), task_test()])
    finally:
        print_suppressions_report()
