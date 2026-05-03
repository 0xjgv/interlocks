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
from interlocks.reports.suppressions import print_suppressions_report
from interlocks.runner import reset_results, results_snapshot, run, run_tasks, warn_skip
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
    """
    start = time.monotonic()
    cfg = load_config()
    reset_results()
    ui.banner(cfg)
    try:
        ui.section("Quality Checks")
        cmd_fix()
        cmd_format()
        ui.section("Parallel")
        parallel = [task_typecheck()]
        test_task = task_test()
        if test_task is None:
            warn_skip("test: no test dir detected — run `interlocks init` to scaffold tests/")
        else:
            parallel.append(test_task)
        if cfg.run_acceptance_in_check:
            acceptance = classify_acceptance_with_details(cfg)
            if acceptance.is_required_failure:
                parallel.append(acceptance_failure_task(acceptance))
            elif acceptance.status is AcceptanceStatus.RUNNABLE:
                acceptance_task = task_acceptance_with_attribution(cfg)
                if acceptance_task is not None:
                    parallel.append(acceptance_task)
        run_tasks(parallel)
        ui.section("Advisory")
        run(task_deps(), no_exit=True)
        cmd_crap_cached_advisory()
        cmd_behavior_attribution_cached_advisory()
    finally:
        print_suppressions_report()
        _print_footer(time.monotonic() - start)


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
