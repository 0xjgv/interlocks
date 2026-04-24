"""Step defs for tests/features/harness_cli.feature.

Shells out to `python -m harness.cli` — same entry point the installed CLI
uses — so this acts as an end-to-end guardrail on the public command surface.
"""

from __future__ import annotations

import subprocess
import sys

from pytest_bdd import given, parsers, scenarios, then

scenarios("../features/harness_cli.feature")


@given(parsers.parse('I run "harness {subcmd}"'), target_fixture="cli_output")
def _run_harness(subcmd: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "harness.cli", *subcmd.split()],
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
