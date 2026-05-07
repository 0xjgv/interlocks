"""Step defs for tests/features/interlock_doctor.feature.

Shells out to `python -m interlocks.cli` — same entry point the installed CLI
uses — mirroring the `_run_interlock` fixture from ``test_interlock_cli``.
"""

from __future__ import annotations

from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then

from tests.step_defs.conftest import interlocks_pythonpath_env, run_interlock_text

scenarios(str(Path(__file__).parent.parent / "features" / "interlock_doctor.feature"))


@given(parsers.parse('I run "interlocks {subcmd}"'), target_fixture="cli_output")
def _run_interlock(subcmd: str) -> str:
    # Point the subprocess at this checkout's interlocks even when an outer
    # interpreter's site-packages shadows it (same concern as test_doctor.py).
    return run_interlock_text(Path.cwd(), *subcmd.split(), env=interlocks_pythonpath_env())


@then(parsers.parse('the output contains "{needle}"'))
def _output_contains(cli_output: str, needle: str) -> None:
    assert needle in cli_output, f"expected {needle!r} in output; got:\n{cli_output}"
