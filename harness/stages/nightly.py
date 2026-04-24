"""Nightly stage: coverage + enforced mutation."""

from __future__ import annotations

import sys
import time

from harness import ui
from harness.config import load_config
from harness.tasks.coverage import cmd_coverage
from harness.tasks.mutation import cmd_mutation


def cmd_nightly() -> None:
    """Long-running gates: coverage + mutation (always blocking on score)."""
    start = time.monotonic()
    cfg = load_config()
    ui.banner(cfg)
    ui.section("Nightly")
    cmd_coverage()
    # Force blocking regardless of `enforce_mutation`: nightly exists to fail the run.
    if not any(a.startswith("--min-score=") for a in sys.argv[1:]):
        sys.argv.append(f"--min-score={cfg.mutation_min_score}")
    cmd_mutation()
    ui.stage_footer(time.monotonic() - start)
