"""Step defs for tests/features/harness_init.feature.

Shells out to `python -m harness.cli init` inside a tmp dir so the scaffold
path exercises the same entry point users hit on the CLI.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../features/harness_init.feature")

_PRE_EXISTING = "# pre-existing pyproject\n"


@dataclass
class InitContext:
    project: Path
    result: subprocess.CompletedProcess[str] | None = None


@given("an empty directory", target_fixture="ctx")
def _empty_dir(tmp_path: Path) -> InitContext:
    return InitContext(project=tmp_path)


@given("a directory containing a pyproject.toml", target_fixture="ctx")
def _dir_with_pyproject(tmp_path: Path) -> InitContext:
    (tmp_path / "pyproject.toml").write_text(_PRE_EXISTING, encoding="utf-8")
    return InitContext(project=tmp_path)


@when(parsers.parse('I run "harness {subcmd}" there'))
def _run_harness(ctx: InitContext, subcmd: str) -> None:
    ctx.result = subprocess.run(
        [sys.executable, "-m", "harness.cli", *subcmd.split()],
        cwd=ctx.project,
        capture_output=True,
        text=True,
        check=False,
    )


@then("the command exits successfully")
def _exit_ok(ctx: InitContext) -> None:
    assert ctx.result is not None
    assert ctx.result.returncode == 0, f"stdout={ctx.result.stdout}\nstderr={ctx.result.stderr}"


@then("the command exits with a non-zero status")
def _exit_fail(ctx: InitContext) -> None:
    assert ctx.result is not None
    assert ctx.result.returncode != 0


@then(parsers.parse('the file "{relpath}" exists'))
def _file_exists(ctx: InitContext, relpath: str) -> None:
    assert (ctx.project / relpath).is_file()


@then(parsers.parse('the file "{relpath}" does not exist'))
def _file_absent(ctx: InitContext, relpath: str) -> None:
    assert not (ctx.project / relpath).exists()


@then("the existing pyproject.toml is unchanged")
def _pyproject_unchanged(ctx: InitContext) -> None:
    assert (ctx.project / "pyproject.toml").read_text(encoding="utf-8") == _PRE_EXISTING
