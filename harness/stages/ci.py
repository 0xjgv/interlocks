"""CI stage — full verification pipeline."""

from __future__ import annotations

from harness.tasks.acceptance import cmd_acceptance
from harness.tasks.arch import cmd_arch
from harness.tasks.audit import cmd_audit
from harness.tasks.complexity import cmd_complexity
from harness.tasks.coverage import cmd_coverage
from harness.tasks.format_check import cmd_format_check
from harness.tasks.lint import cmd_lint
from harness.tasks.typecheck import cmd_typecheck


def cmd_ci() -> None:
    """Full verification: lint, format check, typecheck, tests, acceptance, coverage, arch."""
    print("\n=== CI Checks ===\n")
    cmd_lint()
    cmd_format_check()
    cmd_typecheck()
    cmd_audit()
    cmd_complexity()
    cmd_acceptance()
    cmd_coverage()
    cmd_arch()
