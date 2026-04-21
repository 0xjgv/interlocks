"""Run behave scenarios. Empty features dir warns + exits 0."""

from __future__ import annotations

from pathlib import Path

from harness.paths import TEST_DIR
from harness.runner import run, warn_skip


def cmd_acceptance() -> None:
    """Run behave scenarios. Empty features dir warns + exits 0."""
    features_dir = Path(TEST_DIR) / "features"
    if not features_dir.exists() or not list(features_dir.rglob("*.feature")):
        warn_skip(
            f"Acceptance: no .feature files in {features_dir}/ "
            f"(add one to enable this gate)"
        )
        return
    run("Acceptance (behave)", ["uv", "run", "behave", str(features_dir), "--no-color"])
