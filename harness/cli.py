#!/usr/bin/env python3
"""Project development tasks. Thin dispatcher — imports + TASKS + main()."""

from __future__ import annotations

import re
import sys
import time
import tomllib
from typing import TYPE_CHECKING

from harness import ui
from harness.config import (
    kv_with_source,
    load_config,
    preset_defaults,
    preset_description,
    supported_presets,
)
from harness.runner import fail_skip, ok, preflight
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
from harness.tasks.stats import cmd_trust
from harness.tasks.test import cmd_test
from harness.tasks.typecheck import cmd_typecheck
from harness.tasks.version import cmd_version

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from harness.config import HarnessConfig


def cmd_help() -> None:
    start = time.monotonic()
    cfg = _load_optional_config()
    ui.command_banner("help", cfg)
    ui.section("Usage")
    print("  Usage: harness <command>")
    ui.section("Commands")
    width = max(len(name) for name in TASKS)
    for group_name, group in TASK_GROUPS:
        print()
        print(f"{group_name}:")
        for name, (_, description) in group.items():
            print(f"  {name:<{width}}  {description}")
    _print_detected_block(cfg)
    ui.command_footer(start)


_TOOL_HARNESS_HEADER = re.compile(r"^\[tool\.harness\]\s*$", re.MULTILINE)
_NEXT_HEADER = re.compile(r"^\[", re.MULTILINE)
_PRESET_LINE = re.compile(r"^(?P<indent>[ \t]*)preset\s*=.*$", re.MULTILINE)

_PRESET_REPORTED_KEYS: tuple[str, ...] = (
    "coverage_min",
    "crap_max",
    "complexity_max_ccn",
    "complexity_max_args",
    "complexity_max_loc",
    "mutation_min_coverage",
    "mutation_max_runtime",
    "mutation_min_score",
    "enforce_crap",
    "run_mutation_in_ci",
    "enforce_mutation",
    "mutation_ci_mode",
    "run_acceptance_in_check",
)


def cmd_presets() -> None:
    start = time.monotonic()
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if len(args) >= 2 and args[1] == "set":
        _cmd_presets_set(args[2:], start=start)
        return

    cfg = _load_optional_config()
    ui.command_banner("presets", cfg)
    ui.section("Current")
    ui.kv_block([("preset", cfg.preset if cfg is not None and cfg.preset else "(none)")])
    if cfg is not None:
        ui.section("Current Values")
        ui.kv_block([kv_with_source(cfg, key, getattr(cfg, key)) for key in _PRESET_REPORTED_KEYS])
    ui.section("Available Presets")
    for preset in supported_presets():
        defaults = preset_defaults(preset)
        print(f"  {preset:<8}  {preset_description(preset)}")
        print(
            " " * 12
            + f"coverage>={defaults['coverage_min']}  "
            + f"CRAP<={defaults['crap_max']}  "
            + f"mutation score>={defaults['mutation_min_score']}  "
            + f"mutation_ci={defaults['mutation_ci_mode']}"
        )
    ui.section("Next Steps")
    print("  Set a project preset with the CLI:")
    print()
    print("    harness presets set baseline")
    print()
    print("  Or add this to pyproject.toml:")
    print()
    print('    [tool.harness]\n    preset = "baseline"')
    print()
    print("  Preset thresholds are defaults. You can manually override any threshold")
    print("  in the same [tool.harness] table in pyproject.toml.")
    ui.command_footer(start)


def _cmd_presets_set(args: list[str], *, start: float) -> None:
    presets = supported_presets()
    if len(args) != 1:
        fail_skip(f"usage: harness presets set <{'|'.join(presets)}>")
    preset = args[0]
    if preset not in presets:
        fail_skip(f"unsupported preset: {preset} (expected {'|'.join(presets)})")

    cfg = load_config()
    pyproject = cfg.project_root / "pyproject.toml"
    if not pyproject.is_file():
        fail_skip("presets set: no pyproject.toml — run `harness init` to scaffold")

    ui.command_banner("presets set", cfg)
    ui.section("Preset")
    _write_project_preset(pyproject, preset)
    ok(f"set [tool.harness] preset = {preset!r} in {cfg.relpath(pyproject)}")
    ui.command_footer(start)


def _write_project_preset(pyproject: Path, preset: str) -> None:
    text = pyproject.read_text(encoding="utf-8")
    replacement = f'preset = "{preset}"'
    match = _TOOL_HARNESS_HEADER.search(text)
    if match is None:
        suffix = "" if text.endswith("\n") else "\n"
        pyproject.write_text(f"{text}{suffix}\n[tool.harness]\n{replacement}\n", encoding="utf-8")
        return

    body_start = match.end()
    next_header = _NEXT_HEADER.search(text, body_start)
    body_end = next_header.start() if next_header else len(text)
    body = text[body_start:body_end]
    preset_line = _PRESET_LINE.search(body)
    if preset_line is None:
        insert = f"\n{replacement}" if body.startswith("\n") else f"\n{replacement}\n"
        pyproject.write_text(text[:body_start] + insert + text[body_start:], encoding="utf-8")
        return

    line = f"{preset_line.group('indent')}{replacement}"
    updated_body = body[: preset_line.start()] + line + body[preset_line.end() :]
    pyproject.write_text(text[:body_start] + updated_body + text[body_end:], encoding="utf-8")


def _load_optional_config() -> HarnessConfig | None:
    try:
        return load_config()
    except (OSError, tomllib.TOMLDecodeError):
        return None


def _print_detected_block(cfg: HarnessConfig | None) -> None:
    if cfg is None:
        return
    ui.section("Detected")
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
        ui.section("Config Warnings")
        ui.kv_block([("unsupported preset", p) for p in cfg.unsupported_presets])
    ui.section("Thresholds")
    print("  Override via [tool.harness] or ~/.config/harness/config.toml.")
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
            "presets": (cmd_presets, "Show preset options or set one with `presets set <preset>`"),
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
