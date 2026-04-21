"""Check stage — fix, format, typecheck, test; print suppressions report in finally."""

from __future__ import annotations

from pathlib import Path

from harness.reports.suppressions import print_suppressions_report
from harness.runner import RED, RESET
from harness.tasks.fix import cmd_fix
from harness.tasks.format import cmd_format
from harness.tasks.test import cmd_test
from harness.tasks.typecheck import cmd_typecheck


def _check_hooks_present() -> None:
    """Warn when required hook scripts are missing (drift detection)."""
    required = [
        ".claude/scripts/session-start.sh",
        ".claude/scripts/ups-classify.sh",
        ".claude/scripts/pre-bash-gate.sh",
        ".claude/scripts/pre-edit-gate.sh",
    ]
    missing = [p for p in required if not Path(p).exists()]
    if missing:
        print(f"  {RED}⚠{RESET} Missing hook scripts: {', '.join(missing)}")


def cmd_check() -> None:
    """Fix, format, typecheck, and test the full repo."""
    print("\n=== Quality Checks ===\n")
    try:
        cmd_fix()
        cmd_format()
        cmd_typecheck()
        cmd_test()
        _check_hooks_present()
    finally:
        print_suppressions_report()
