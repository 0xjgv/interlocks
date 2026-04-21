#!/usr/bin/env python3
"""Project development tasks. Zero dependencies — stdlib only."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from harness.reports.suppressions import print_suppressions_report
from harness.runner import RED, RESET, run
from harness.stages.post_edit import cmd_post_edit
from harness.stages.pre_commit import cmd_pre_commit
from harness.tasks.acceptance import cmd_acceptance
from harness.tasks.arch import cmd_arch
from harness.tasks.audit import cmd_audit
from harness.tasks.complexity import cmd_complexity
from harness.tasks.coverage import cmd_coverage
from harness.tasks.crap import cmd_crap
from harness.tasks.fix import cmd_fix
from harness.tasks.format import cmd_format
from harness.tasks.format_check import cmd_format_check
from harness.tasks.lint import cmd_lint
from harness.tasks.mutation import cmd_mutation
from harness.tasks.test import cmd_test
from harness.tasks.typecheck import cmd_typecheck

if TYPE_CHECKING:
    from collections.abc import Callable

# ── Commands ──────────────────────────────────────────────────────


# ── Stages ────────────────────────────────────────────────────────


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


def cmd_hooks() -> None:
    """Install git pre-commit hook."""
    hook = Path(".git/hooks/pre-commit")
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\nuv run harness pre-commit\n", encoding="utf-8")
    hook.chmod(0o755)
    print("Installed pre-commit hook")


def cmd_clean() -> None:
    """Remove cache and build artifacts."""
    print("\n=== Cleaning Up ===\n")
    for name in [".ruff_cache", "build", "dist", "htmlcov"]:
        p = Path(name)
        if p.is_dir():
            shutil.rmtree(p)
    for name in [".coverage"]:
        p = Path(name)
        if p.is_file():
            p.unlink()
    for p in Path().rglob("__pycache__"):
        shutil.rmtree(p)
    run("Ruff clean", ["uv", "run", "ruff", "clean"])


# ── CLI dispatch ──────────────────────────────────────────────────

TASKS: dict[str, tuple[Callable[..., None], str]] = {
    "fix": (cmd_fix, "Fix lint errors with ruff"),
    "format": (cmd_format, "Format code with ruff"),
    "lint": (cmd_lint, "Lint code with ruff (read-only)"),
    "typecheck": (cmd_typecheck, "Type-check with basedpyright"),
    "test": (cmd_test, "Run tests with unittest"),
    "check": (cmd_check, "Fix + format + typecheck + test (full repo)"),
    "pre-commit": (cmd_pre_commit, "Staged checks + tests"),
    "ci": (cmd_ci, "Full verification: lint, typecheck, tests, acceptance, coverage, arch"),
    "audit": (cmd_audit, "Audit dependencies for known vulnerabilities"),
    "acceptance": (cmd_acceptance, "Run acceptance scenarios (behave)"),
    "coverage": (cmd_coverage, "Tests with coverage threshold (--min=N)"),
    "mutation": (cmd_mutation, "Mutation testing (mutmut, advisory)"),
    "crap": (cmd_crap, "CRAP complexity x coverage gate (advisory)"),
    "arch": (cmd_arch, "Architecture checks (import-linter)"),
    "post-edit": (cmd_post_edit, "Format if source files changed (Claude Code hook)"),
    "setup-hooks": (cmd_hooks, "Install git pre-commit hook"),
    "clean": (cmd_clean, "Remove cache and build artifacts"),
}


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]

    if not args:
        cmd_check()
        return

    task_name = args[0]
    if task_name not in TASKS:
        print(f"Unknown command: {task_name}")
        sys.exit(1)

    TASKS[task_name][0]()


if __name__ == "__main__":
    main()
