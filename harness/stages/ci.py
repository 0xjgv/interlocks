"""CI stage — full verification pipeline."""

from __future__ import annotations

from harness.tasks.complexity import cmd_complexity
from harness.tasks.coverage import cmd_coverage
from harness.tasks.format_check import cmd_format_check
from harness.tasks.lint import cmd_lint
from harness.tasks.typecheck import cmd_typecheck


def cmd_ci() -> None:
    """Full verification: format_check, lint, complexity, typecheck, coverage."""
    print("\n=== CI Checks ===\n")
    cmd_format_check()
    cmd_lint()
    cmd_complexity()
    cmd_typecheck()
    cmd_coverage(min_pct=80)
