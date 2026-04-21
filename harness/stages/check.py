"""Check stage — fix, format, typecheck, test; print suppressions report in finally."""

from __future__ import annotations

from harness.reports.suppressions import print_suppressions_report
from harness.tasks.fix import cmd_fix
from harness.tasks.format import cmd_format
from harness.tasks.test import cmd_test
from harness.tasks.typecheck import cmd_typecheck


def cmd_check() -> None:
    """Fix, format, typecheck, and test the full repo."""
    print("\n=== Quality Checks ===\n")
    try:
        cmd_fix()
        cmd_format()
        cmd_typecheck()
        cmd_test()
    finally:
        print_suppressions_report()
