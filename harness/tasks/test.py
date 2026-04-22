"""Run tests with unittest."""

from __future__ import annotations

from harness.paths import TEST_DIR
from harness.runner import python_m, run


def cmd_test() -> None:
    run("Run tests", python_m("unittest", "discover", "-s", TEST_DIR, "-q"))
