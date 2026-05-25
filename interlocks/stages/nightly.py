"""Nightly stage: coverage + properties + audit + enforced mutation."""

from __future__ import annotations

import time

from interlocks import ui
from interlocks.config import load_config
from interlocks.runner import print_stage_verdict, reset_results, results_snapshot, stage_json
from interlocks.skip import current_skip_policy, maybe_print_skip_banner, run_unless_skipped
from interlocks.tasks.audit import cmd_audit
from interlocks.tasks.coverage import cmd_coverage
from interlocks.tasks.mutation import cmd_mutation
from interlocks.tasks.properties import cmd_properties


def cmd_nightly() -> None:
    """Long-running gates: coverage + properties + audit + mutation."""
    start = time.monotonic()
    cfg = load_config()
    reset_results()
    skip_policy = current_skip_policy()
    ui.banner(cfg)
    maybe_print_skip_banner(skip_policy)
    ui.section("Nightly")
    try:
        run_unless_skipped(
            "coverage",
            lambda: cmd_coverage(
                include_properties=not skip_policy.enabled("properties"),
                property_profile="nightly",
            ),
            skip_policy,
        )
        if skip_policy.enabled("coverage") or skip_policy.enabled("properties"):
            run_unless_skipped(
                "properties",
                lambda: cmd_properties(profile_default="nightly"),
                skip_policy,
            )
        run_unless_skipped("audit", lambda: cmd_audit(allow_network_skip=True), skip_policy)
        # Force blocking regardless of `enforce_mutation`: nightly exists to fail the run.
        run_unless_skipped(
            "mutation", lambda: cmd_mutation(min_score_default=cfg.mutation_min_score), skip_policy
        )
    finally:
        elapsed = time.monotonic() - start
        if ui.is_json():
            passed = all(result.status == "ok" for result in results_snapshot())
            ui.print_json(stage_json("nightly", passed=passed, elapsed=elapsed))
        else:
            ui.stage_footer(elapsed)
            print_stage_verdict("nightly", elapsed)
