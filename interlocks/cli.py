#!/usr/bin/env python3
"""Project development tasks. Thin dispatcher — imports + TASKS + main()."""

from __future__ import annotations

import re
import sys
import time
from typing import TYPE_CHECKING

from interlocks import ui
from interlocks.config import (
    clear_cache,
    kv_with_source,
    load_config,
    load_optional_config,
    preset_defaults,
    preset_description,
    supported_presets,
)
from interlocks.crash import CrashBoundary
from interlocks.runner import fail_skip, ok, preflight
from interlocks.stages.check import cmd_check
from interlocks.stages.ci import cmd_ci
from interlocks.stages.clean import cmd_clean
from interlocks.stages.nightly import cmd_nightly
from interlocks.stages.post_edit import cmd_post_edit
from interlocks.stages.pre_commit import cmd_pre_commit
from interlocks.stages.setup_hooks import cmd_hooks
from interlocks.tasks.acceptance import cmd_acceptance
from interlocks.tasks.agents import cmd_agents
from interlocks.tasks.arch import cmd_arch
from interlocks.tasks.audit import cmd_audit
from interlocks.tasks.behavior_attribution import cmd_behavior_attribution
from interlocks.tasks.config import cmd_config
from interlocks.tasks.coverage import cmd_coverage
from interlocks.tasks.crap import cmd_crap
from interlocks.tasks.deps import cmd_deps
from interlocks.tasks.deps_freshness import cmd_deps_freshness
from interlocks.tasks.doctor import cmd_doctor
from interlocks.tasks.evaluate import cmd_evaluate
from interlocks.tasks.fix import cmd_fix
from interlocks.tasks.format import cmd_format
from interlocks.tasks.init import cmd_init
from interlocks.tasks.init_acceptance import cmd_init_acceptance
from interlocks.tasks.lint import cmd_lint
from interlocks.tasks.mutation import cmd_mutation
from interlocks.tasks.setup import cmd_setup
from interlocks.tasks.setup_skill import cmd_setup_skill
from interlocks.tasks.stats import cmd_trust
from interlocks.tasks.test import cmd_test
from interlocks.tasks.typecheck import cmd_typecheck
from interlocks.tasks.version import cmd_version

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from interlocks.config import InterlockConfig


def cmd_help() -> None:
    start = time.monotonic()
    cfg = load_optional_config()
    ui.command_banner("help", cfg)
    ui.section("Usage")
    print("  Usage: interlocks <command>")
    ui.section("Commands")
    width = max(len(name) for name in TASKS) + 2
    for group_name, group in TASK_GROUPS:
        print()
        print(f"{group_name}:")
        for name, (_, description) in group.items():
            tag = f"[{name}]"
            print(f"  {tag:<{width}}  {description}{_alias_suffix(name)}")
    _print_detected_block(cfg)
    ui.command_footer(start)


def cmd_task_help(task_name: str) -> None:
    start = time.monotonic()
    cfg = load_optional_config()
    _, description = TASKS[task_name]
    ui.command_banner("help", cfg)
    ui.section("Usage")
    print(f"  Usage: interlocks {task_name}")
    ui.section("Command")
    print(f"  [{task_name}]  {description}{_alias_suffix(task_name)}")
    ui.command_footer(start)


_TOOL_INTERLOCK_HEADER = re.compile(r"^\[tool\.interlocks\]\s*$", re.MULTILINE)
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
    "enforce_behavior_attribution",
    "run_mutation_in_ci",
    "enforce_mutation",
    "mutation_ci_mode",
    "run_acceptance_in_check",
    "require_acceptance",
)


def cmd_presets() -> None:
    start = time.monotonic()
    if _maybe_handle_presets_set(start):
        return
    _cmd_presets_list(start)


def _maybe_handle_presets_set(start: float) -> bool:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args or args[0] != "presets":
        args = ["presets"]
    if len(args) >= 2 and args[1] == "set":
        _cmd_presets_set(args[2:], start=start)
        return True
    if len(args) == 2:
        _cmd_presets_set([args[1]], start=start)
        return True
    if len(args) > 2:
        fail_skip(_presets_usage())
    return False


def _cmd_presets_list(start: float) -> None:
    cfg = load_optional_config()
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
    print("    interlocks presets set baseline")
    print()
    print("  Or add this to pyproject.toml:")
    print()
    print('    [tool.interlocks]\n    preset = "baseline"')
    print()
    print("  Preset thresholds are defaults. You can manually override any threshold")
    print("  in the same [tool.interlocks] table in pyproject.toml.")
    ui.command_footer(start)


def _presets_usage() -> str:
    choices = "|".join(supported_presets())
    return f"usage: interlocks presets [<{choices}>] or interlocks presets set <{choices}>"


def _cmd_presets_set(args: list[str], *, start: float) -> None:
    presets = supported_presets()
    choices = "|".join(presets)
    if len(args) != 1:
        fail_skip(f"usage: interlocks presets set <{choices}>")
    preset = args[0]
    if preset not in presets:
        fail_skip(f"unsupported preset: {preset} (expected {choices})")

    cfg = load_config()
    pyproject = cfg.project_root / "pyproject.toml"
    if not pyproject.is_file():
        fail_skip("presets set: no pyproject.toml — run `interlocks init` to scaffold")

    ui.command_banner("presets set", cfg)
    ui.section("Preset")
    _write_project_preset(pyproject, preset)
    clear_cache()
    ok(f"set [tool.interlocks] preset = {preset!r} in {cfg.relpath(pyproject)}")
    ui.command_footer(start)


def _write_project_preset(pyproject: Path, preset: str) -> None:
    text = pyproject.read_text(encoding="utf-8")
    replacement = f'preset = "{preset}"'
    match = _TOOL_INTERLOCK_HEADER.search(text)
    if match is None:
        suffix = "" if text.endswith("\n") else "\n"
        body = f"{text}{suffix}\n[tool.interlocks]\n{replacement}\n"
        pyproject.write_text(body, encoding="utf-8")
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


ALIASES: dict[str, str] = {"attribution": "behavior-attribution"}


def _alias_suffix(name: str) -> str:
    aliases = sorted(alias for alias, canonical in ALIASES.items() if canonical == name)
    if not aliases:
        return ""
    label = "alias" if len(aliases) == 1 else "aliases"
    return f" ({label}: {', '.join(aliases)})"


def _print_detected_block(cfg: InterlockConfig | None) -> None:
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
    print("  Override via [tool.interlocks] in pyproject.toml.")
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
        ("enforce_behavior_attribution", str(cfg.enforce_behavior_attribution)),
        ("run_mutation_in_ci", str(cfg.run_mutation_in_ci)),
        ("enforce_mutation", str(cfg.enforce_mutation)),
    ])
    ui.section("Crash Reports")
    print("  Local cache: ~/.cache/interlocks/crashes/")
    print("  On internal crashes, interactive terminals prompt before opening a GitHub issue.")


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
            "deps-freshness": (
                cmd_deps_freshness,
                "Check outdated dependencies via explicit package-index lookup",
            ),
            "arch": (cmd_arch, "Architectural contracts (import-linter; default: src ↛ tests)"),
            "acceptance": (
                cmd_acceptance,
                "Gherkin acceptance tests (pytest-bdd default; behave auto-detected)",
            ),
            "behavior-attribution": (
                cmd_behavior_attribution,
                "Verify BDD scenarios reach symbols declared by claimed behaviors",
            ),
            "init-acceptance": (
                cmd_init_acceptance,
                "Scaffold tests/features + tests/step_defs (pytest-bdd layout)",
            ),
            "coverage": (cmd_coverage, "Tests with coverage threshold (--min=N)"),
            "crap": (cmd_crap, "CRAP complexity x coverage gate"),
            "mutation": (
                cmd_mutation,
                "Mutation testing via mutmut (advisory; see `interlocks nightly`)",
            ),
        },
    ),
    (
        "Stages",
        {
            "check": (cmd_check, "Fix + format + typecheck + test (full repo)"),
            "pre-commit": (cmd_pre_commit, "Staged checks + tests"),
            "ci": (cmd_ci, "Full verification: lint, audit, typecheck, tests, coverage, CRAP"),
            "nightly": (cmd_nightly, "Long-running gates: coverage + mutation (blocking)"),
            "post-edit": (cmd_post_edit, "Format if source files changed (Claude Code hook)"),
            "setup-hooks": (cmd_hooks, "Install git pre-commit and Claude Stop hooks"),
            "clean": (cmd_clean, "Remove cache, build, coverage, and generated artifacts"),
        },
    ),
    (
        "Reports",
        {
            "trust": (
                cmd_trust,
                "Actionable trust report: coverage, CRAP, suspicious tests, next actions",
            ),
            "evaluate": (
                cmd_evaluate,
                "Score automatable quality checklist items",
            ),
        },
    ),
    (
        "Utility",
        {
            "config": (
                cmd_config,
                "Show all [tool.interlocks] keys with defaults and current values",
            ),
            "doctor": (cmd_doctor, "Preflight diagnostic: paths, tools, venv"),
            "setup": (cmd_setup, "Install/check hooks, agent docs, and Claude skill"),
            "init": (cmd_init, "Scaffold a greenfield pyproject.toml + tests/ in CWD"),
            "agents": (
                cmd_agents,
                "Register interlocks block in AGENTS.md / CLAUDE.md (idempotent)",
            ),
            "setup-skill": (
                cmd_setup_skill,
                "Install bundled Claude Code SKILL.md (idempotent)",
            ),
            "presets": (cmd_presets, "Show preset options or set one with `presets set <preset>`"),
            "version": (cmd_version, "print interlocks version"),
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
    raw_args = sys.argv[1:]
    args = [a for a in raw_args if not a.startswith("-")]

    if not args:
        cmd_help()
        return

    requested = args[0]
    task_name = ALIASES.get(requested, requested)
    if task_name not in TASKS:
        print(f"Unknown command: {requested}", file=sys.stderr)
        cmd_help()
        sys.exit(1)

    if any(a in ("-h", "--help") for a in raw_args):
        cmd_task_help(task_name)
        return

    preflight(task_name)
    boundary = CrashBoundary(subcommand=task_name)
    with boundary:
        boundary.maybe_inject_for_test()
        TASKS[task_name][0]()


if __name__ == "__main__":
    main()
