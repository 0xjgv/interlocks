"""Nightly stage: coverage + enforced mutation."""

from __future__ import annotations

import sys

from harness.config import load_config
from harness.runner import section
from harness.tasks.coverage import cmd_coverage
from harness.tasks.mutation import cmd_mutation


def cmd_nightly() -> None:
    """Long-running gates: coverage + mutation (always blocking on score)."""
    section("Nightly")
    cmd_coverage()
    # Force blocking regardless of `enforce_mutation`: nightly exists to fail the run.
    if not any(a.startswith("--min-score=") for a in sys.argv[1:]):
        sys.argv.append(f"--min-score={load_config().mutation_min_score}")
    cmd_mutation()
