"""Step defs for tests/features/interlock_doctor.feature.

Shells out to `python -m interlock.cli` — same entry point the installed CLI
uses — mirroring the `_run_interlock` fixture from ``test_interlock_cli``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then

import interlock

scenarios(str(Path(__file__).parent.parent / "features" / "interlock_doctor.feature"))

# Point the subprocess at this checkout's interlock even when an outer
# interpreter's site-packages shadows it (same concern as test_doctor.py).
_INTERLOCK_PARENT = str(Path(interlock.__file__).resolve().parent.parent)


@given(parsers.parse('I run "interlock {subcmd}"'), target_fixture="cli_output")
def _run_interlock(subcmd: str) -> str:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{_INTERLOCK_PARENT}{os.pathsep}{existing}" if existing else _INTERLOCK_PARENT
    )
    result = subprocess.run(
        [sys.executable, "-m", "interlock.cli", *subcmd.split()],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    return result.stdout + result.stderr


@then(parsers.parse('the output contains "{needle}"'))
def _output_contains(cli_output: str, needle: str) -> None:
    assert needle in cli_output, f"expected {needle!r} in output; got:\n{cli_output}"
