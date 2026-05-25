"""Check stage."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from interlocks import run_summary, ui
from interlocks.acceptance_status import (
    AcceptanceStatus,
    acceptance_failure_task,
    classify_acceptance_with_details,
)
from interlocks.config import (
    InterlockConfig,
    load_config,
    project_env_ready,
)
from interlocks.git import changed_py_files_vs
from interlocks.reports.suppressions import print_suppressions_report
from interlocks.runner import (
    Task,
    arg_flag_value,
    print_stage_verdict,
    record_skip,
    reset_results,
    results_snapshot,
    run,
    run_tasks,
    stage_json,
    warn_skip,
)
from interlocks.skip import (
    SkipPolicy,
    current_skip_policy,
    maybe_print_skip_banner,
    run_unless_skipped,
)
from interlocks.stages._budgeted import run_budgeted_mutation
from interlocks.tasks.acceptance import task_acceptance_with_attribution
from interlocks.tasks.behavior_attribution import cmd_behavior_attribution_cached_advisory
from interlocks.tasks.crap import cmd_crap_cached_advisory
from interlocks.tasks.deps import task_deps
from interlocks.tasks.properties import task_properties
from interlocks.tasks.test import task_test
from interlocks.tasks.typecheck import task_typecheck

if TYPE_CHECKING:
    from pathlib import Path


def cmd_check() -> None:
    """Fix, format (serial — both mutate files), then typecheck + test in parallel.

    ``deps`` runs advisory at the end: fast feedback on dep hygiene without
    halting the edit loop on deptry noise. CI is where it gates.

    ``--changed[=<ref>]`` scopes file-level gates (fix/format/typecheck/CRAP) to
    ``.py`` files changed vs ``<ref>`` (default ``cfg.changed_ref``). Graph-wide
    gates (deps, behavior-attribution, acceptance), property tests, and the test
    suite skip — they can't be scoped to a file list without re-introducing the
    legacy noise.
    """
    start = time.monotonic()
    cfg = load_config()
    skip_policy = current_skip_policy()
    reset_results()
    run_summary.reset()

    scope_ref = arg_flag_value("--changed", cfg.changed_ref)
    scoped_files = sorted(changed_py_files_vs(scope_ref)) if scope_ref else None

    ui.banner(cfg)
    if _exit_if_changed_scope_empty(scope_ref, scoped_files, start):
        return
    _print_scope(scope_ref, scoped_files)
    maybe_print_skip_banner(skip_policy)

    try:
        _run_check_sections(cfg, scope_ref, scoped_files, skip_policy)
    finally:
        print_suppressions_report()
        run_summary.flush(cfg)
        _print_footer(time.monotonic() - start)


def _run_check_sections(
    cfg: InterlockConfig,
    scope_ref: str | None,
    scoped_files: list[str] | None,
    skip_policy: SkipPolicy,
) -> None:
    ui.section("Quality Checks")
    _run_budgeted_mutation(base=scope_ref or "HEAD", skip_policy=skip_policy)
    ui.section("Parallel")
    run_tasks(_parallel_tasks(cfg, scope_ref, scoped_files))
    ui.section("Advisory")
    _run_advisory(scope_ref, scoped_files, skip_policy)


def _exit_if_changed_scope_empty(
    scope_ref: str | None,
    scoped_files: list[str] | None,
    start: float,
) -> bool:
    if scope_ref is None or scoped_files:
        return False
    ui.section("Quality Checks")
    if ui.is_verbose() and not ui.is_json():
        print(f"  scope=changed vs {scope_ref} — no Python files changed; nothing to check")
    _print_footer(time.monotonic() - start)
    return True


def _print_scope(scope_ref: str | None, scoped_files: list[str] | None) -> None:
    if scoped_files and ui.is_verbose() and not ui.is_json():
        ui.section("Scope")
        print(f"  changed vs {scope_ref} — {len(scoped_files)} file(s)")


def _parallel_tasks(
    cfg: InterlockConfig, scope_ref: str | None, scoped_files: list[str] | None
) -> list[Task]:
    acceptance = _acceptance_task(cfg, scope_ref)
    properties = _properties_task(cfg, scope_ref)
    optional = (
        task_typecheck(scoped_files),
        _test_task(cfg, scope_ref, acceptance, properties),
        acceptance,
        properties,
    )
    return [t for t in optional if t is not None]


def _test_task(
    cfg: InterlockConfig,
    scope_ref: str | None,
    acceptance: Task | None,
    properties: Task | None,
) -> Task | None:
    if scope_ref is not None:
        _skip_under_changed(
            "test",
            "full-suite, not file-level",
            "Run `interlocks test` for the full suite.",
        )
        return None
    if not project_env_ready(cfg):
        return None
    test = task_test(
        extra_pytest_args=(
            *_acceptance_ignore_args(cfg, acceptance),
            *_properties_ignore_args(cfg, properties),
        )
    )
    if test is None:
        record_skip("test", "no test dir detected — run `interlocks init` to scaffold tests/")
        warn_skip("test: no test dir detected — run `interlocks init` to scaffold tests/")
    return test


def _acceptance_ignore_args(cfg: InterlockConfig, acceptance: Task | None) -> tuple[str, ...]:
    if acceptance is None or acceptance.description != "Acceptance (pytest-bdd)":
        return ()
    if cfg.features_dir is None or cfg.test_runner != "pytest":
        return ()
    candidates = (cfg.features_dir, cfg.features_dir.parent / "step_defs")
    return tuple(
        f"--ignore={cfg.relpath(path)}" for path in candidates if _collected_by_test(cfg, path)
    )


def _properties_ignore_args(cfg: InterlockConfig, properties: Task | None) -> tuple[str, ...]:
    if properties is None or cfg.properties_dir is None or cfg.test_runner != "pytest":
        return ()
    if not _collected_by_test(cfg, cfg.properties_dir):
        return ()
    return (f"--ignore={cfg.relpath(cfg.properties_dir)}",)


def _collected_by_test(cfg: InterlockConfig, path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        path.resolve().relative_to(cfg.test_dir.resolve())
    except ValueError:
        return False
    return True


def _acceptance_task(cfg: InterlockConfig, scope_ref: str | None) -> Task | None:
    if not project_env_ready(cfg):
        return None
    if not cfg.run_acceptance_in_check:
        return None
    if scope_ref is not None:
        _skip_under_changed(
            "acceptance",
            "scenario-level, not file-level",
            "Run `interlocks acceptance` for full scenario coverage.",
        )
        return None
    acceptance = classify_acceptance_with_details(cfg)
    if acceptance.is_required_failure:
        return acceptance_failure_task(acceptance)
    if acceptance.status is AcceptanceStatus.RUNNABLE:
        return task_acceptance_with_attribution(cfg)
    return None


def _properties_task(cfg: InterlockConfig, scope_ref: str | None) -> Task | None:
    if not project_env_ready(cfg):
        return None
    if not cfg.run_properties_in_check:
        return None
    if scope_ref is not None:
        _skip_under_changed(
            "properties",
            "property-wide, not file-level",
            "Run `interlocks properties --profile=check` for generated-input coverage.",
        )
        return None
    return task_properties(profile="check")


def _run_advisory(
    scope_ref: str | None, scoped_files: list[str] | None, skip_policy: SkipPolicy
) -> None:
    if scope_ref is None:
        run_unless_skipped("deps", lambda: run(task_deps(), no_exit=True), skip_policy)
    else:
        _skip_under_changed(
            "deps",
            "graph-wide by construction",
            "Run `interlocks deps` for dependency graph checks.",
        )
    run_unless_skipped(
        "crap",
        lambda: cmd_crap_cached_advisory(set(scoped_files) if scoped_files is not None else None),
        skip_policy,
    )
    if scope_ref is None:
        run_unless_skipped("attribution", cmd_behavior_attribution_cached_advisory, skip_policy)
    else:
        _skip_under_changed(
            "attribution",
            "registry-wide",
            "Run `interlocks behavior-attribution` for registry-wide attribution.",
        )


def _skip_under_changed(label: str, reason: str, next_action: str) -> None:
    record_skip(label, f"skipped under --changed — {reason}", next_action=next_action)
    warn_skip(f"{label}: skipped under --changed — {reason}")


def _run_budgeted_mutation(*, base: str, skip_policy: SkipPolicy) -> None:
    run_budgeted_mutation(base=base, emit_legacy_rows=True, skip_policy=skip_policy)


def _print_footer(elapsed: float) -> None:
    """Always emit the one-line verdict; verbose adds the chrome footer."""
    ui.stage_footer(elapsed)
    print_stage_verdict("check", elapsed)
    if ui.is_json():
        ui.print_json(stage_json("check", passed=_check_passed(), elapsed=elapsed))


def _check_passed() -> bool:
    """True when no recorded gate failed — mirrors the human verdict's pass test."""
    return all(r.status == "ok" for r in results_snapshot())
