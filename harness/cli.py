#!/usr/bin/env python3
"""Project development tasks. Thin dispatcher — imports + TASKS + main()."""

from __future__ import annotations

import sys
import tomllib
from typing import TYPE_CHECKING

from harness.config import load_config
from harness.stages.check import cmd_check
from harness.stages.ci import cmd_ci
from harness.stages.clean import cmd_clean
from harness.stages.nightly import cmd_nightly
from harness.stages.post_edit import cmd_post_edit
from harness.stages.pre_commit import cmd_pre_commit
from harness.stages.setup_hooks import cmd_hooks
from harness.tasks.acceptance import cmd_acceptance
from harness.tasks.arch import cmd_arch
from harness.tasks.audit import cmd_audit
from harness.tasks.coverage import cmd_coverage
from harness.tasks.crap import cmd_crap
from harness.tasks.deps import cmd_deps
from harness.tasks.fix import cmd_fix
from harness.tasks.format import cmd_format
from harness.tasks.init_acceptance import cmd_init_acceptance
from harness.tasks.lint import cmd_lint
from harness.tasks.mutation import cmd_mutation
from harness.tasks.test import cmd_test
from harness.tasks.typecheck import cmd_typecheck

if TYPE_CHECKING:
    from collections.abc import Callable


def cmd_help() -> None:
    width = max(len(name) for name in TASKS)
    print("Usage: harness <command>")
    for group_name, group in TASK_GROUPS:
        print()
        print(f"{group_name}:")
        for name, (_, description) in group.items():
            print(f"  {name:<{width}}  {description}")
    _print_detected_block()


def _print_detected_block() -> None:
    try:
        cfg = load_config()
    except (OSError, tomllib.TOMLDecodeError):
        return
    print()
    print("Detected:")
    print(f"  project_root           {cfg.project_root}")
    print(f"  src_dir                {cfg.src_dir_arg}")
    print(f"  test_dir               {cfg.test_dir_arg}")
    print(f"  test_runner            {cfg.test_runner}")
    print(f"  test_invoker           {cfg.test_invoker}")
    if cfg.pytest_args:
        print(f"  pytest_args            {list(cfg.pytest_args)}")
    if cfg.features_dir_arg is not None:
        print(f"  features_dir           {cfg.features_dir_arg}")
    if cfg.acceptance_runner is not None:
        print(f"  acceptance_runner      {cfg.acceptance_runner}")
    print()
    print("Thresholds (override via [tool.harness] or ~/.config/harness/config.toml):")
    print(f"  coverage_min           {cfg.coverage_min}")
    print(f"  crap_max               {cfg.crap_max}")
    print(f"  complexity_max_ccn     {cfg.complexity_max_ccn}")
    print(f"  complexity_max_args    {cfg.complexity_max_args}")
    print(f"  complexity_max_loc     {cfg.complexity_max_loc}")
    print(f"  mutation_min_coverage  {cfg.mutation_min_coverage}")
    print(f"  mutation_max_runtime   {cfg.mutation_max_runtime}")
    print(f"  mutation_min_score     {cfg.mutation_min_score}")
    print(f"  enforce_crap           {cfg.enforce_crap}")
    print(f"  run_mutation_in_ci     {cfg.run_mutation_in_ci}")
    print(f"  enforce_mutation       {cfg.enforce_mutation}")


TASK_GROUPS: list[tuple[str, dict[str, tuple[Callable[..., None], str]]]] = [
    (
        "Tasks",
        {
            "fix": (cmd_fix, "Fix lint errors with ruff"),
            "format": (cmd_format, "Format code with ruff"),
            "lint": (cmd_lint, "Lint code with ruff (read-only)"),
            "typecheck": (cmd_typecheck, "Type-check with basedpyright"),
            "test": (cmd_test, "Run tests (auto-detects pytest vs unittest)"),
            "audit": (cmd_audit, "Audit dependencies for known vulnerabilities"),
            "deps": (cmd_deps, "Dep hygiene: unused/missing/transitive (deptry)"),
            "arch": (cmd_arch, "Architectural contracts (import-linter; default: src ↛ tests)"),
            "acceptance": (
                cmd_acceptance,
                "Gherkin acceptance tests (pytest-bdd default; behave auto-detected)",
            ),
            "init-acceptance": (
                cmd_init_acceptance,
                "Scaffold tests/features + tests/step_defs (pytest-bdd layout)",
            ),
            "coverage": (cmd_coverage, "Tests with coverage threshold (--min=N)"),
            "crap": (cmd_crap, "CRAP complexity x coverage gate"),
            "mutation": (
                cmd_mutation,
                "Mutation testing via mutmut (advisory; see `harness nightly`)",
            ),
        },
    ),
    (
        "Stages",
        {
            "check": (cmd_check, "Fix + format + typecheck + test (full repo)"),
            "pre-commit": (cmd_pre_commit, "Staged checks + tests"),
            "ci": (cmd_ci, "Full verification: lint, typecheck, tests, coverage, CRAP"),
            "nightly": (cmd_nightly, "Long-running gates: coverage + mutation (blocking)"),
            "post-edit": (cmd_post_edit, "Format if source files changed (Claude Code hook)"),
            "setup-hooks": (cmd_hooks, "Install git pre-commit and Claude Stop hooks"),
            "clean": (cmd_clean, "Remove cache and build artifacts"),
        },
    ),
    (
        "Other",
        {
            "help": (cmd_help, "Show this help message"),
        },
    ),
]

TASKS: dict[str, tuple[Callable[..., None], str]] = {
    name: entry for _, group in TASK_GROUPS for name, entry in group.items()
}


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]

    if not args:
        cmd_help()
        return

    task_name = args[0]
    if task_name not in TASKS:
        print(f"Unknown command: {task_name}", file=sys.stderr)
        cmd_help()
        sys.exit(1)

    TASKS[task_name][0]()


if __name__ == "__main__":
    main()
