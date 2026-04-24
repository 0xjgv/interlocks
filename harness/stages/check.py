"""Check stage."""

from __future__ import annotations

import time

from harness import ui
from harness.config import load_config
from harness.reports.suppressions import print_suppressions_report
from harness.runner import run, run_tasks, warn_skip
from harness.tasks.acceptance import task_acceptance
from harness.tasks.crap import cmd_crap_cached_advisory
from harness.tasks.deps import task_deps
from harness.tasks.fix import cmd_fix
from harness.tasks.format import cmd_format
from harness.tasks.test import task_test
from harness.tasks.typecheck import task_typecheck


def cmd_check() -> None:
    """Fix, format (serial — both mutate files), then typecheck + test in parallel.

    ``deps`` runs advisory at the end: fast feedback on dep hygiene without
    halting the edit loop on deptry noise. CI is where it gates.
    """
    start = time.monotonic()
    cfg = load_config()
    ui.banner(cfg)
    try:
        ui.section("Quality Checks")
        cmd_fix()
        cmd_format()
        ui.section("Parallel")
        parallel = [task_typecheck()]
        test_task = task_test()
        if test_task is None:
            warn_skip("test: no test dir detected — run `harness init` to scaffold tests/")
        else:
            parallel.append(test_task)
        if cfg.run_acceptance_in_check:
            acceptance = task_acceptance()
            if acceptance is not None:
                parallel.append(acceptance)
        run_tasks(parallel)
        ui.section("Advisory")
        run(task_deps(), no_exit=True)
        cmd_crap_cached_advisory()
    finally:
        print_suppressions_report()
        ui.stage_footer(time.monotonic() - start)
