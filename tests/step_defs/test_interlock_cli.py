"""Step defs for tests/features/interlock_cli.feature.

Shells out to `python -m interlock.cli` — same entry point the installed CLI
uses — so this acts as an end-to-end guardrail on the public command surface.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then

scenarios(str(Path(__file__).parent.parent / "features" / "interlock_cli.feature"))


@given(parsers.parse('I run "interlock {subcmd}"'), target_fixture="cli_output")
def _run_interlock(subcmd: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "interlock.cli", *subcmd.split()],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout + result.stderr


@then(parsers.parse('the output lists the command "{name}"'))
def _lists_command(cli_output: str, name: str) -> None:
    tag = f"[{name}]"
    assert f"  {tag} " in cli_output or f"  {tag}\n" in cli_output, (
        f"expected {tag!r} in help output; got:\n{cli_output}"
    )


@then(parsers.parse('the output contains "{needle}"'))
def _output_contains(cli_output: str, needle: str) -> None:
    assert needle in cli_output, f"expected {needle!r} in output; got:\n{cli_output}"


@then(parsers.parse('the output does not contain "{needle}"'))
def _output_does_not_contain(cli_output: str, needle: str) -> None:
    assert needle not in cli_output, f"did not expect {needle!r} in output; got:\n{cli_output}"
