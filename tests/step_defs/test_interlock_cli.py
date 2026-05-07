"""Step defs for tests/features/interlock_cli.feature.

Shells out to `python -m interlocks.cli` — same entry point the installed CLI
uses — so this acts as an end-to-end guardrail on the public command surface.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then

from tests.step_defs.conftest import run_interlock_text

scenarios(str(Path(__file__).parent.parent / "features" / "interlock_cli.feature"))


@given(parsers.parse('I run "interlocks {subcmd}"'), target_fixture="cli_output")
def _run_interlock(subcmd: str) -> str:
    return run_interlock_text(Path.cwd(), *subcmd.split())


@given(
    parsers.parse('I run "interlocks {subcmd}" on a project with a traceability gap'),
    target_fixture="cli_output",
)
def _run_interlock_with_traceability_gap(subcmd: str, tmp_path: Path) -> str:
    _write_traceability_gap_project(tmp_path)
    return run_interlock_text(tmp_path, *subcmd.split())


def _write_traceability_gap_project(root: Path) -> None:
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests" / "features").mkdir(parents=True)
    (root / "tests" / "features" / "checkout.feature").write_text(
        "Feature: checkout\n\n  Scenario: paid order succeeds\n    Given buyer has cart\n",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "traceability-gap"
            version = "0.0.0"

            [tool.interlocks]
            src_dir = "pkg"
            test_dir = "tests"
            """
        ),
        encoding="utf-8",
    )


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
