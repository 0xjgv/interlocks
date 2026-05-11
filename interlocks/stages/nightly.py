"""Nightly stage: coverage + audit + enforced mutation."""

from __future__ import annotations

import time

from interlocks import ui
from interlocks.config import load_config
from interlocks.runner import print_stage_verdict, reset_results
from interlocks.skip import current_skip_policy, maybe_print_skip_banner, run_unless_skipped
from interlocks.tasks.audit import cmd_audit
from interlocks.tasks.coverage import cmd_coverage
from interlocks.tasks.mutation import cmd_mutation


def cmd_nightly() -> None:
    """Long-running gates: coverage + audit + mutation (always blocking on score)."""
    start = time.monotonic()
    cfg = load_config()
    reset_results()
    skip_policy = current_skip_policy()
    ui.banner(cfg)
    maybe_print_skip_banner(skip_policy)
    ui.section("Nightly")
    try:
        run_unless_skipped("coverage", cmd_coverage, skip_policy)
        run_unless_skipped("audit", lambda: cmd_audit(allow_network_skip=True), skip_policy)
        # Force blocking regardless of `enforce_mutation`: nightly exists to fail the run.
        run_unless_skipped(
            "mutation", lambda: cmd_mutation(min_score_default=cfg.mutation_min_score), skip_policy
        )
    finally:
        elapsed = time.monotonic() - start
        ui.stage_footer(elapsed)
        print_stage_verdict("nightly", elapsed)
