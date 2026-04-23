"""Step defs for tests/features/harness_doctor.feature.

Shells out to `python -m harness.cli` — same entry point the installed CLI
uses — mirroring the `_run_harness` fixture from ``test_harness_cli``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then

import harness

scenarios("../features/harness_doctor.feature")

# Point the subprocess at this checkout's harness even when an outer
# interpreter's site-packages shadows it (same concern as test_doctor.py).
_HARNESS_PARENT = str(Path(harness.__file__).resolve().parent.parent)


@given(parsers.parse('I run "harness {subcmd}"'), target_fixture="cli_output")
def _run_harness(subcmd: str) -> str:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{_HARNESS_PARENT}{os.pathsep}{existing}" if existing else _HARNESS_PARENT
    result = subprocess.run(
        [sys.executable, "-m", "harness.cli", *subcmd.split()],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    return result.stdout + result.stderr


@then(parsers.parse('the output contains "{needle}"'))
def _output_contains(cli_output: str, needle: str) -> None:
    assert needle in cli_output, f"expected {needle!r} in output; got:\n{cli_output}"
