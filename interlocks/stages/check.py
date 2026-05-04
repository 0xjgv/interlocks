"""Check stage."""

from __future__ import annotations

import time

from interlocks import ui
from interlocks.acceptance_status import (
    AcceptanceStatus,
    acceptance_failure_task,
    classify_acceptance_with_details,
)
from interlocks.config import load_config
from interlocks.git import changed_py_files_vs
from interlocks.reports.suppressions import print_suppressions_report
from interlocks.runner import (
    arg_flag_value,
    reset_results,
    results_snapshot,
    run,
    run_tasks,
    warn_skip,
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
    reset_results()

    scope_ref = arg_flag_value("--changed", cfg.changed_ref)
    scoped_files = sorted(changed_py_files_vs(scope_ref)) if scope_ref else None

    ui.banner(cfg)
    if scope_ref is not None and not scoped_files:
        ui.section("Quality Checks")
        print(f"  scope=changed vs {scope_ref} — no Python files changed; nothing to check")
        _print_footer(time.monotonic() - start)
        return
    if scoped_files:
        ui.section("Scope")
        print(f"  changed vs {scope_ref} — {len(scoped_files)} file(s)")

    try:
        ui.section("Quality Checks")
        cmd_fix(scoped_files)
        cmd_format(scoped_files)
        ui.section("Parallel")
        parallel = [task_typecheck(scoped_files)]
        if scope_ref is None:
            test_task = task_test()
            if test_task is None:
                warn_skip("test: no test dir detected — run `interlocks init` to scaffold tests/")
            else:
                parallel.append(test_task)
        else:
            _skip_under_changed("test", "run `interlocks test` for full suite")
        if cfg.run_acceptance_in_check and scope_ref is None:
            acceptance = classify_acceptance_with_details(cfg)
            if acceptance.is_required_failure:
                parallel.append(acceptance_failure_task(acceptance))
            elif acceptance.status is AcceptanceStatus.RUNNABLE:
                acceptance_task = task_acceptance_with_attribution(cfg)
                if acceptance_task is not None:
                    parallel.append(acceptance_task)
        elif cfg.run_acceptance_in_check:
            _skip_under_changed("acceptance", "scenario-level, not file-level")
        run_tasks(parallel)
        ui.section("Advisory")
        if scope_ref is None:
            run(task_deps(), no_exit=True)
        else:
            _skip_under_changed("deps", "graph-wide by construction")
        cmd_crap_cached_advisory(set(scoped_files) if scoped_files is not None else None)
        if scope_ref is None:
            cmd_behavior_attribution_cached_advisory()
        else:
            _skip_under_changed("attribution", "registry-wide")
    finally:
        print_suppressions_report()
        _print_footer(time.monotonic() - start)


def _skip_under_changed(label: str, reason: str) -> None:
    warn_skip(f"{label}: skipped under --changed — {reason}")


def _print_footer(elapsed: float) -> None:
    """Verdict line when quiet (agent/LLM path); standard stage footer otherwise."""
    if not ui.is_quiet():
        ui.stage_footer(elapsed)
        return
    results = results_snapshot()
    fails = [label for label, ok in results if not ok]
    if not fails:
        print(f"check: ok — {len(results)} tasks, {elapsed:.1f}s")
        return
    detail = ", ".join(fails)
    print(f"check: FAILED — {detail} ({len(fails)} of {len(results)}) — {elapsed:.1f}s")
