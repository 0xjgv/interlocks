"""Check stage."""

from __future__ import annotations

import time

from interlocks import run_summary, ui
from interlocks.acceptance_status import (
    AcceptanceStatus,
    acceptance_failure_task,
    classify_acceptance_with_details,
)
from interlocks.config import (
    CREATE_PROJECT_ENV_HINT,
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
    reset_results,
    run,
    run_tasks,
    warn_skip,
)
from interlocks.skip import (
    SkipPolicy,
    current_skip_policy,
    maybe_print_skip_banner,
    run_unless_skipped,
)
from interlocks.tasks.acceptance import task_acceptance_with_attribution
from interlocks.tasks.behavior_attribution import cmd_behavior_attribution_cached_advisory
from interlocks.tasks.crap import cmd_crap_cached_advisory
from interlocks.tasks.deps import task_deps
from interlocks.tasks.fix import cmd_fix
from interlocks.tasks.format import cmd_format
from interlocks.tasks.test import task_test
from interlocks.tasks.typecheck import task_typecheck


def cmd_check() -> None:
    """Fix, format (serial — both mutate files), then typecheck + test in parallel.

    ``deps`` runs advisory at the end: fast feedback on dep hygiene without
    halting the edit loop on deptry noise. CI is where it gates.

    ``--changed[=<ref>]`` scopes file-level gates (fix/format/typecheck/CRAP) to
    ``.py`` files changed vs ``<ref>`` (default ``cfg.changed_ref``). Graph-wide
    gates (deps, behavior-attribution, acceptance) and the test suite skip — they
    can't be scoped to a file list without re-introducing the legacy noise.
    """
    start = time.monotonic()
    cfg = load_config()
    skip_policy = current_skip_policy()
    reset_results()
    run_summary.reset()

    scope_ref = arg_flag_value("--changed", cfg.changed_ref)
    scoped_files = sorted(changed_py_files_vs(scope_ref)) if scope_ref else None

    ui.banner(cfg)
    if scope_ref is not None and not scoped_files:
        ui.section("Quality Checks")
        if ui.is_verbose():
            print(f"  scope=changed vs {scope_ref} — no Python files changed; nothing to check")
        _print_footer(time.monotonic() - start)
        return
    if scoped_files and ui.is_verbose():
        ui.section("Scope")
        print(f"  changed vs {scope_ref} — {len(scoped_files)} file(s)")

    maybe_print_skip_banner(skip_policy)

    try:
        ui.section("Quality Checks")
        run_unless_skipped("fix", lambda: cmd_fix(scoped_files), skip_policy)
        run_unless_skipped("format", lambda: cmd_format(scoped_files), skip_policy)
        ui.section("Parallel")
        run_tasks(_parallel_tasks(cfg, scope_ref, scoped_files))
        ui.section("Advisory")
        _run_advisory(scope_ref, scoped_files, skip_policy)
    finally:
        print_suppressions_report()
        run_summary.flush(cfg)
        _print_footer(time.monotonic() - start)


def _parallel_tasks(
    cfg: InterlockConfig, scope_ref: str | None, scoped_files: list[str] | None
) -> list[Task]:
    if not project_env_ready(cfg):
        warn_skip(
            "typecheck, test: skipped — no project environment. Create one "
            f"{CREATE_PROJECT_ENV_HINT}, then re-run — `interlocks doctor` has details."
        )
        return []
    tasks = [task_typecheck(scoped_files)]
    optional = (_test_task(scope_ref), _acceptance_task(cfg, scope_ref))
    tasks.extend(t for t in optional if t is not None)
    return tasks


def _test_task(scope_ref: str | None) -> Task | None:
    if scope_ref is not None:
        _skip_under_changed("test", "run `interlocks test` for full suite")
        return None
    test = task_test()
    if test is None:
        warn_skip("test: no test dir detected — run `interlocks init` to scaffold tests/")
    return test


def _acceptance_task(cfg: InterlockConfig, scope_ref: str | None) -> Task | None:
    if not cfg.run_acceptance_in_check:
        return None
    if scope_ref is not None:
        _skip_under_changed("acceptance", "scenario-level, not file-level")
        return None
    acceptance = classify_acceptance_with_details(cfg)
    if acceptance.is_required_failure:
        return acceptance_failure_task(acceptance)
    if acceptance.status is AcceptanceStatus.RUNNABLE:
        return task_acceptance_with_attribution(cfg)
    return None


def _run_advisory(
    scope_ref: str | None, scoped_files: list[str] | None, skip_policy: SkipPolicy
) -> None:
    if scope_ref is None:
        run_unless_skipped("deps", lambda: run(task_deps(), no_exit=True), skip_policy)
    else:
        _skip_under_changed("deps", "graph-wide by construction")
    run_unless_skipped(
        "crap",
        lambda: cmd_crap_cached_advisory(set(scoped_files) if scoped_files is not None else None),
        skip_policy,
    )
    if scope_ref is None:
        run_unless_skipped("attribution", cmd_behavior_attribution_cached_advisory, skip_policy)
    else:
        _skip_under_changed("attribution", "registry-wide")


def _skip_under_changed(label: str, reason: str) -> None:
    warn_skip(f"{label}: skipped under --changed — {reason}")


def _print_footer(elapsed: float) -> None:
    """Always emit the one-line verdict; verbose adds the chrome footer."""
    ui.stage_footer(elapsed)
    print_stage_verdict("check", elapsed)
