#!/usr/bin/env python3
"""Project development tasks. Thin dispatcher — imports + TASKS + main()."""

from __future__ import annotations

import sys
import tomllib
from typing import TYPE_CHECKING

from harness import ui
from harness.config import load_config
from harness.runner import preflight
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
from harness.tasks.doctor import cmd_doctor
from harness.tasks.fix import cmd_fix
from harness.tasks.format import cmd_format
from harness.tasks.init import cmd_init
from harness.tasks.init_acceptance import cmd_init_acceptance
from harness.tasks.lint import cmd_lint
from harness.tasks.mutation import cmd_mutation
from harness.tasks.stats import cmd_stats, cmd_trust
from harness.tasks.test import cmd_test
from harness.tasks.typecheck import cmd_typecheck
from harness.tasks.version import cmd_version

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
    detected: list[tuple[str, str]] = [
        ("preset", cfg.preset or "(none)"),
        ("project_root", str(cfg.project_root)),
        ("src_dir", cfg.src_dir_arg),
        ("test_dir", cfg.test_dir_arg),
        ("test_runner", cfg.test_runner),
        ("test_invoker", cfg.test_invoker),
    ]
    if cfg.pytest_args:
        detected.append(("pytest_args", str(list(cfg.pytest_args))))
    if cfg.features_dir_arg is not None:
        detected.append(("features_dir", cfg.features_dir_arg))
    if cfg.acceptance_runner is not None:
        detected.append(("acceptance_runner", cfg.acceptance_runner))
    ui.kv_block(detected)
    if cfg.unsupported_presets:
        print()
        print("Config warnings:")
        ui.kv_block([("unsupported preset", p) for p in cfg.unsupported_presets])
    print()
    print("Thresholds (override via [tool.harness] or ~/.config/harness/config.toml):")
    ui.kv_block([
        ("coverage_min", str(cfg.coverage_min)),
        ("crap_max", str(cfg.crap_max)),
        ("complexity_max_ccn", str(cfg.complexity_max_ccn)),
        ("complexity_max_args", str(cfg.complexity_max_args)),
        ("complexity_max_loc", str(cfg.complexity_max_loc)),
        ("mutation_min_coverage", str(cfg.mutation_min_coverage)),
        ("mutation_max_runtime", str(cfg.mutation_max_runtime)),
        ("mutation_min_score", str(cfg.mutation_min_score)),
        ("enforce_crap", str(cfg.enforce_crap)),
        ("run_mutation_in_ci", str(cfg.run_mutation_in_ci)),
        ("enforce_mutation", str(cfg.enforce_mutation)),
    ])


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
        "Reports",
        {
            "stats": (
                cmd_stats,
                "Legacy alias for trust report (cached quality data)",
            ),
            "trust": (
                cmd_trust,
                "Actionable trust report: coverage, CRAP, suspicious tests, next actions",
            ),
        },
    ),
    (
        "Utility",
        {
            "doctor": (cmd_doctor, "Preflight diagnostic: paths, tools, venv"),
            "init": (cmd_init, "Scaffold a greenfield pyproject.toml + tests/ in CWD"),
            "version": (cmd_version, "print pyharness version"),
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

    preflight(task_name)
    TASKS[task_name][0]()


if __name__ == "__main__":
    main()
