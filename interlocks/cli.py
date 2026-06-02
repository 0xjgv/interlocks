#!/usr/bin/env python3
"""Project development tasks. Thin dispatcher — imports + TASKS + main()."""

from __future__ import annotations

import re
import sys
from typing import TYPE_CHECKING

from interlocks import ui
from interlocks.command_docs import (
    ALIASES,
    COMMAND_DOCS_BY_NAME,
    COMMAND_GROUPS,
    alias_suffix,
    command_doc_payload,
    command_index_payload,
    command_usage,
    unknown_task_flags,
)
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
from interlocks.runner import fail_skip, preflight
from interlocks.skip import validate_cli_skip
from interlocks.stages.check import cmd_check
from interlocks.stages.ci import cmd_ci
from interlocks.stages.clean import cmd_clean
from interlocks.stages.nightly import cmd_nightly
from interlocks.stages.post_edit import cmd_post_edit
from interlocks.stages.pre_commit import cmd_pre_commit
from interlocks.tasks.acceptance import cmd_acceptance
from interlocks.tasks.arch import cmd_arch
from interlocks.tasks.audit import cmd_audit
from interlocks.tasks.baseline_cmd import cmd_baseline
from interlocks.tasks.behavior_attribution import cmd_behavior_attribution
from interlocks.tasks.complexity import cmd_complexity
from interlocks.tasks.config import cmd_config
from interlocks.tasks.coverage import cmd_coverage
from interlocks.tasks.crap import cmd_crap
from interlocks.tasks.deps import cmd_deps
from interlocks.tasks.deps_freshness import cmd_deps_freshness
from interlocks.tasks.doctor import cmd_doctor
from interlocks.tasks.evaluate import cmd_evaluate
from interlocks.tasks.explain import cmd_explain
from interlocks.tasks.fix import cmd_fix
from interlocks.tasks.fix_annotate import cmd_fix_annotate
from interlocks.tasks.fix_metrics import cmd_fix_metrics
from interlocks.tasks.fix_optimize import cmd_fix_optimize
from interlocks.tasks.fix_plan import cmd_fix_plan
from interlocks.tasks.fix_replay import cmd_fix_replay
from interlocks.tasks.fix_rule import cmd_fix_rule
from interlocks.tasks.format import cmd_format
from interlocks.tasks.format_check import cmd_format_check
from interlocks.tasks.init import cmd_init
from interlocks.tasks.lint import cmd_lint
from interlocks.tasks.mutation import cmd_mutation
from interlocks.tasks.properties import cmd_properties
from interlocks.tasks.property_candidates import cmd_property_candidates
from interlocks.tasks.setup import cmd_setup
from interlocks.tasks.stats import cmd_trust
from interlocks.tasks.test import cmd_test
from interlocks.tasks.typecheck import cmd_typecheck
from interlocks.tasks.version import cmd_version
from interlocks.tasks.warm import cmd_warm

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from interlocks.config import InterlockConfig, Preset


def cmd_help(*, advanced: bool = False) -> None:
    cfg = load_optional_config()
    if ui.is_json():
        ui.print_json(_help_payload(cfg, advanced=advanced))
        return
    ui.section("Usage")
    print("  Usage: interlocks <command>")
    if advanced:
        ui.section("Commands")
        width = max(len(name) for name in TASKS) + 2
        for group_name, group in TASK_GROUPS:
            ui.group_header(group_name)
            for name, (_, description) in group.items():
                _print_command_row(name, description, width)
    else:
        names = _help_group_command_names()
        width = max(len(name) for name in names) + 2
        for group_name, group_names in _HELP_GROUPS:
            ui.group_header(group_name)
            for name in group_names:
                _, description = TASKS[name]
                _print_command_row(name, description, width)
        ui.section("More")
        print("  Run `interlocks help --advanced` to see the full command catalog.")
    _print_detected_block(cfg)


def cmd_task_help(task_name: str) -> None:
    if ui.is_json():
        ui.print_json(_task_help_payload(task_name))
        return
    _, description = TASKS[task_name]
    doc = COMMAND_DOCS_BY_NAME.get(task_name)
    usage = command_usage(doc) if doc is not None else task_name
    ui.section("Usage")
    print(f"  Usage: interlocks {usage}")
    ui.section("Command")
    _print_command_row(task_name, description, len(task_name) + 2)
    if doc is not None and doc.flags:
        ui.section("Flags")
        width = max(len(spec.name) for spec in doc.flags) + 2
        kind_width = max(len(spec.kind) + 1 for spec in doc.flags)
        kind_width = max(kind_width, 9)
        for spec in doc.flags:
            default = f" (default: {spec.default})" if spec.default else ""
            print(f"  {spec.name:<{width}}  {spec.kind:<{kind_width}}{spec.description}{default}")


def cmd_gate_help() -> None:
    names = _nested_command_names("gate")
    if ui.is_json():
        ui.print_json({
            **_task_help_payload("gate"),
            "subcommands": [_help_command_payload(name) for name in names],
        })
        return
    cmd_task_help("gate")
    ui.section("Gates")
    width = max(len(name) for name in names) + 2
    for name in names:
        _, description = TASKS[name]
        _print_command_row(name, description, width)


def cmd_hook_help() -> None:
    names = _nested_command_names("hook")
    if ui.is_json():
        ui.print_json({
            **_task_help_payload("hook"),
            "subcommands": [_help_command_payload(name) for name in names],
        })
        return
    cmd_task_help("hook")
    ui.section("Hooks")
    width = max(len(name) for name in names) + 2
    for name in names:
        _, description = TASKS[name]
        _print_command_row(name, description, width)


def _nested_command_names(parent: str) -> tuple[str, ...]:
    prefix = parent + " "
    return tuple(name for _, group in TASK_GROUPS for name in group if name.startswith(prefix))


def cmd_help_from_argv() -> None:
    positionals = [arg for arg in sys.argv[1:] if not arg.startswith("-")]
    if positionals and ALIASES.get(positionals[0], positionals[0]) == "help":
        target = positionals[1:]
        if target:
            task_name = _resolve_help_target(target)
            if task_name not in TASKS:
                fail_skip(f"help: unknown command {' '.join(target)!r}")
            cmd_task_help(task_name)
            return
    cmd_help(advanced="--advanced" in sys.argv[1:])


def _resolve_help_target(target: list[str]) -> str:
    if len(target) >= 2:
        requested = f"{target[0]} {target[1]}"
        resolved = ALIASES.get(requested, requested)
        if resolved in TASKS:
            return resolved
    requested = target[0]
    return ALIASES.get(requested, requested)


def _help_payload(cfg: InterlockConfig | None, *, advanced: bool) -> dict[str, object]:
    return {
        "command": "help",
        "usage": "usage: interlocks help [--advanced | <command>]",
        "advanced": advanced,
        "groups": _help_groups_payload(advanced=advanced),
        "detected": _detected_payload(cfg),
    }


def _help_groups_payload(*, advanced: bool) -> list[dict[str, object]]:
    if advanced:
        groups = [(group_name, tuple(group)) for group_name, group in TASK_GROUPS]
    else:
        groups = list(_HELP_GROUPS)
    return [
        {
            "name": group_name,
            "commands": [_help_command_payload(name) for name in names],
        }
        for group_name, names in groups
    ]


def _help_command_payload(name: str) -> dict[str, object]:
    doc = COMMAND_DOCS_BY_NAME.get(name)
    if doc is not None:
        return command_index_payload(doc)
    _, description = TASKS[name]
    return {"name": name, "summary": description, "aliases": []}


def _detected_payload(cfg: InterlockConfig | None) -> dict[str, object]:
    if cfg is None or not (cfg.project_root / "pyproject.toml").is_file():
        return {"pyproject": False}
    return {
        "pyproject": True,
        "preset": cfg.preset,
        "src": cfg.src_dir_arg,
        "tests": cfg.test_dir_arg,
        "runner": cfg.test_runner,
    }


_TOOL_INTERLOCK_HEADER = re.compile(r"^\[tool\.interlocks\]\s*$", re.MULTILINE)
_NEXT_HEADER = re.compile(r"^\[", re.MULTILINE)
_PRESET_LINE = re.compile(r"^(?P<indent>[ \t]*)preset\s*=.*$", re.MULTILINE)

_THRESHOLD_KEYS: tuple[str, ...] = (
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
)

# `presets` reports a superset of `_THRESHOLD_KEYS` — the extra keys are
# preset-only signals that don't appear in `cmd_help`'s threshold block.
_PRESET_REPORTED_KEYS: tuple[str, ...] = (
    *_THRESHOLD_KEYS,
    "mutation_ci_mode",
    "run_acceptance_in_check",
    "run_properties_in_check",
    "require_acceptance",
)


def cmd_presets() -> None:
    if _maybe_handle_presets_set():
        return
    _cmd_presets_list()


def _maybe_handle_presets_set() -> bool:
    raw = [a for a in sys.argv[1:] if not a.startswith("-")]
    # Trailing args only carry preset selection when invoked as `... presets ...`.
    args = raw[1:] if raw and raw[0] == "presets" else []
    if not args:
        return False
    if args[0] == "set":
        _cmd_presets_set(args[1:])
    elif len(args) == 1:
        _cmd_presets_set(args)
    else:
        _fail_presets_error("invalid usage", _presets_usage())
    return True


def _cmd_presets_list() -> None:
    cfg = load_optional_config()
    if ui.is_json():
        ui.print_json(_presets_payload(cfg))
        return
    ui.section("Current")
    ui.kv_block([("preset", cfg.preset if cfg is not None and cfg.preset else "(none)")])
    project_cfg = _preset_project_config(cfg)
    if project_cfg is not None:
        ui.section("Current Values")
        ui.kv_block([
            kv_with_source(project_cfg, key, getattr(project_cfg, key))
            for key in _PRESET_REPORTED_KEYS
        ])
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
    print()
    print(f"Switch with: {_presets_set_invocation()}")
    if not ui.is_verbose():
        return
    ui.section("Next Steps")
    print("  Set a project preset with the CLI:")
    print()
    print("    interlocks presets set progressive")
    print()
    print("  Or add this to pyproject.toml:")
    print()
    print('    [tool.interlocks]\n    preset = "progressive"')
    print()
    print("  Preset thresholds are defaults. You can manually override any threshold")
    print("  in the same [tool.interlocks] table in pyproject.toml.")


def _presets_set_invocation() -> str:
    """The canonical `interlocks presets set <...>` phrase."""
    choices = "|".join(supported_presets())
    return f"interlocks presets set <{choices}>"


def _presets_usage() -> str:
    choices = "|".join(supported_presets())
    return f"usage: interlocks presets [<{choices}>] or {_presets_set_invocation()}"


def _cmd_presets_set(args: list[str]) -> None:
    presets = supported_presets()
    choices = "|".join(presets)
    if len(args) != 1:
        _fail_presets_error("invalid usage", f"usage: {_presets_set_invocation()}")
    preset = args[0]
    if preset not in presets:
        _fail_presets_error(
            f"unsupported preset: {preset}",
            f"expected {choices}",
        )

    cfg = load_config()
    pyproject = cfg.project_root / "pyproject.toml"
    if not pyproject.is_file():
        _fail_presets_error(
            "no pyproject.toml",
            "Run `interlocks init` to scaffold.",
        )

    _write_project_preset(pyproject, preset)
    clear_cache()
    if ui.is_json():
        ui.print_json({
            "command": "presets",
            "action": "set",
            "preset": preset,
            "pyproject_path": cfg.relpath(pyproject),
        })
        return
    print(f"set [tool.interlocks] preset = {preset!r} in {cfg.relpath(pyproject)}")


def _presets_payload(cfg: InterlockConfig | None) -> dict[str, object]:
    return {
        "command": "presets",
        "current": _current_preset_payload(cfg),
        "current_values": _preset_current_values_payload(cfg),
        "available_presets": [_available_preset_payload(preset) for preset in supported_presets()],
        "switch_command": _presets_set_invocation(),
    }


def _current_preset_payload(cfg: InterlockConfig | None) -> dict[str, object]:
    project_cfg = _preset_project_config(cfg)
    if project_cfg is None:
        return {"pyproject": False, "preset": None}
    return {
        "pyproject": True,
        "preset": project_cfg.preset,
        "pyproject_path": project_cfg.relpath(project_cfg.project_root / "pyproject.toml"),
    }


def _preset_current_values_payload(cfg: InterlockConfig | None) -> list[dict[str, object]]:
    project_cfg = _preset_project_config(cfg)
    if project_cfg is None:
        return []
    return [
        {
            "key": key,
            "value": getattr(project_cfg, key),
            "source": project_cfg.value_sources.get(key, "unknown"),
        }
        for key in _PRESET_REPORTED_KEYS
    ]


def _preset_project_config(cfg: InterlockConfig | None) -> InterlockConfig | None:
    if cfg is None or not (cfg.project_root / "pyproject.toml").is_file():
        return None
    return cfg


def _available_preset_payload(preset: Preset) -> dict[str, object]:
    return {
        "name": preset,
        "description": preset_description(preset),
        "defaults": preset_defaults(preset),
    }


def _presets_error_payload(error: str, detail: str) -> dict[str, object]:
    return {
        "command": "presets",
        "error": error,
        "detail": detail,
        "usage": _presets_usage(),
        "expected_presets": list(supported_presets()),
    }


def _fail_presets_error(error: str, detail: str) -> None:
    if ui.is_json():
        ui.print_json(_presets_error_payload(error, detail))
        sys.exit(1)
    fail_skip(f"{error} ({detail})" if detail.startswith("expected ") else detail)


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


_HELP_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Start here", ("doctor", "setup", "check", "ci", "nightly")),
    ("Direct access", ("gate", "fix")),
    ("Project", ("init", "config", "presets", "explain", "clean", "version")),
)


def _help_group_command_names() -> tuple[str, ...]:
    names = tuple(name for _, group_names in _HELP_GROUPS for name in group_names)
    missing = [name for name in names if name not in TASKS]
    if missing:
        missing_names = ", ".join(sorted(missing))
        raise RuntimeError(f"help group references unknown command(s): {missing_names}")
    return names


def _print_command_row(name: str, description: str, width: int) -> None:
    tag = f"[{name}]"
    print(f"  {tag:<{width}}  {description}{alias_suffix(name)}")


def _detected_summary_line(cfg: InterlockConfig) -> str:
    """One-line `Detected:` summary for default-mode `help`."""
    return (
        f"Detected: preset={cfg.preset or '(none)'}, "
        f"src={cfg.src_dir_arg}, "
        f"tests={cfg.test_dir_arg}, "
        f"runner={cfg.test_runner}"
    )


def _print_detected_block(cfg: InterlockConfig | None) -> None:
    # `load_optional_config` returns `None` only on a malformed/unreadable
    # pyproject.toml; a *missing* one still yields a fallback config rooted at
    # CWD, so the "no pyproject.toml" signal is the on-disk file check.
    if cfg is None or not (cfg.project_root / "pyproject.toml").is_file():
        print("Detected: (no pyproject.toml)")
        return
    print(_detected_summary_line(cfg))
    if not ui.is_verbose():
        return
    _print_verbose_detected_block(cfg)


def _print_verbose_detected_block(cfg: InterlockConfig) -> None:
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
    ui.kv_block([(key, str(getattr(cfg, key))) for key in _THRESHOLD_KEYS])
    ui.section("Crash Reports")
    print("  Local cache: ~/.cache/interlocks/crashes/")
    print("  On internal crashes, interactive terminals prompt before opening a GitHub issue.")


TASK_HANDLERS: dict[str, Callable[..., None]] = {
    "baseline": cmd_baseline,
    "check": cmd_check,
    "ci": cmd_ci,
    "clean": cmd_clean,
    "config": cmd_config,
    "doctor": cmd_doctor,
    "evaluate": cmd_evaluate,
    "explain": cmd_explain,
    "fix": cmd_fix,
    "fix annotate": cmd_fix_annotate,
    "fix metrics": cmd_fix_metrics,
    "fix optimize": cmd_fix_optimize,
    "fix plan": cmd_fix_plan,
    "fix replay": cmd_fix_replay,
    "fix rule": cmd_fix_rule,
    "gate": cmd_gate_help,
    "gate acceptance": cmd_acceptance,
    "gate arch": cmd_arch,
    "gate audit": cmd_audit,
    "gate behavior-attribution": cmd_behavior_attribution,
    "gate complexity": cmd_complexity,
    "gate coverage": cmd_coverage,
    "gate crap": cmd_crap,
    "gate deps": cmd_deps,
    "gate deps-freshness": cmd_deps_freshness,
    "gate format": cmd_format,
    "gate format-check": cmd_format_check,
    "gate lint": cmd_lint,
    "gate mutation": cmd_mutation,
    "gate properties": cmd_properties,
    "gate test": cmd_test,
    "gate typecheck": cmd_typecheck,
    "help": cmd_help_from_argv,
    "hook": cmd_hook_help,
    "hook post-edit": cmd_post_edit,
    "hook pre-commit": cmd_pre_commit,
    "init": cmd_init,
    "nightly": cmd_nightly,
    "presets": cmd_presets,
    "property-candidates": cmd_property_candidates,
    "setup": cmd_setup,
    "trust": cmd_trust,
    "version": cmd_version,
    "warm": cmd_warm,
}


def _task_groups_from_docs() -> list[tuple[str, dict[str, tuple[Callable[..., None], str]]]]:
    return [
        (
            group_name,
            {
                name: (TASK_HANDLERS[name], COMMAND_DOCS_BY_NAME[name].summary)
                for name in group_names
            },
        )
        for group_name, group_names in COMMAND_GROUPS
    ]


TASK_GROUPS: list[tuple[str, dict[str, tuple[Callable[..., None], str]]]] = (
    _task_groups_from_docs()
)

TASKS: dict[str, tuple[Callable[..., None], str]] = {
    name: entry for _, group in TASK_GROUPS for name, entry in group.items()
}

_NESTED_COMMANDS: frozenset[str] = frozenset({"fix", "gate", "hook"})


def main() -> None:
    raw_args = sys.argv[1:]
    if "--quiet" in raw_args:
        _fail_quiet_removed()
    task_name = _resolve_task_name(raw_args)
    if task_name is None:
        return
    if _maybe_render_task_help(task_name, raw_args):
        return
    _validate_task_flags(task_name, raw_args)
    validate_cli_skip()
    preflight(task_name)
    boundary = CrashBoundary(subcommand=task_name)
    with boundary:
        boundary.maybe_inject_for_test()
        TASKS[task_name][0]()


def _resolve_task_name(raw_args: list[str]) -> str | None:
    args = [a for a in raw_args if not a.startswith("-")]
    if not args:
        if ui.is_json():
            _fail_missing_command()
        cmd_help_from_argv()
        return None
    task_name = _match_task_name(args)
    if task_name is None:
        requested = " ".join(args[:2]) if args[0] in _NESTED_COMMANDS else args[0]
        _fail_unknown_command(requested)
    return task_name


def _match_task_name(positionals: list[str]) -> str | None:
    if len(positionals) >= 2:
        requested = f"{positionals[0]} {positionals[1]}"
        task_name = ALIASES.get(requested, requested)
        if task_name in TASKS:
            return task_name
        if positionals[0] in _NESTED_COMMANDS:
            return None
    requested = positionals[0]
    task_name = ALIASES.get(requested, requested)
    if task_name in TASKS:
        return task_name
    return None


def _maybe_render_task_help(task_name: str, raw_args: list[str]) -> bool:
    if "-h" not in raw_args and "--help" not in raw_args:
        return False
    if ui.is_json():
        ui.print_json(_task_help_payload(task_name))
    else:
        cmd_task_help(task_name)
    return True


def _validate_task_flags(task_name: str, raw_args: list[str]) -> None:
    bad = unknown_task_flags(task_name, raw_args)
    if bad:
        _fail_unknown_flag(task_name, bad[0])


def _unknown_command_payload(requested: str) -> dict[str, object]:
    return {
        "command": requested,
        "error": f"unknown command {requested}",
        "usage": "usage: interlocks <command>",
        "known_commands": sorted(TASKS),
    }


def _missing_command_payload() -> dict[str, object]:
    return {
        "command": "interlocks",
        "error": "missing command",
        "usage": "usage: interlocks <command>",
        "known_commands": sorted(TASKS),
    }


def _task_help_payload(task_name: str) -> dict[str, object]:
    doc = COMMAND_DOCS_BY_NAME.get(task_name)
    if doc is None:
        return {
            "command": task_name,
            "usage": f"usage: interlocks {task_name}",
            "flags": [],
        }
    return command_doc_payload(doc)


def _fail_missing_command() -> None:
    ui.print_json(_missing_command_payload())
    sys.exit(1)


def _quiet_removed_payload() -> dict[str, object]:
    return {
        "command": "interlocks",
        "error": "--quiet was removed; minimal output is the default",
        "next_action": "Remove `--quiet`; pass `--verbose` for full output.",
    }


def _fail_quiet_removed() -> None:
    if ui.is_json():
        ui.print_json(_quiet_removed_payload())
        sys.exit(1)
    print(
        "interlocks: --quiet was removed; minimal output is the default. "
        "Pass --verbose for full output.",
        file=sys.stderr,
    )
    sys.exit(1)


def _fail_unknown_command(requested: str) -> None:
    if ui.is_json():
        ui.print_json(_unknown_command_payload(requested))
        sys.exit(1)
    print(f"Unknown command: {requested}", file=sys.stderr)
    cmd_help()
    sys.exit(1)


def _unknown_flag_payload(task_name: str, flag: str) -> dict[str, object]:
    doc = COMMAND_DOCS_BY_NAME.get(task_name)
    payload: dict[str, object] = {
        "command": task_name,
        "error": f"unknown flag {flag}",
        "flag": flag,
    }
    if doc is not None:
        payload["usage"] = f"usage: interlocks {command_usage(doc)}"
        payload["known_flags"] = [spec.name for spec in doc.flags]
    return payload


def _fail_unknown_flag(task_name: str, flag: str) -> None:
    if ui.is_json():
        ui.print_json(_unknown_flag_payload(task_name, flag))
        sys.exit(1)
    print(f"interlocks {task_name}: unknown flag {flag}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
