"""Step defs for tests/features/interlock_agents.feature.

Shells out to `python -m interlocks.cli agents` inside a tmp dir so the
file-mutation path exercises the same entry point users hit on the CLI.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then, when

from tests.step_defs.conftest import run_interlock_in_cwd

scenarios(str(Path(__file__).parent.parent / "features" / "interlock_agents.feature"))


@dataclass
class AgentsContext:
    project: Path
    result: subprocess.CompletedProcess[str] | None = None


@given("an empty directory", target_fixture="ctx")
def _empty_dir(tmp_path: Path) -> AgentsContext:
    return AgentsContext(project=tmp_path)


@given(
    parsers.parse('a directory with AGENTS.md "{agents_text}" and CLAUDE.md "{claude_text}"'),
    target_fixture="ctx",
)
def _seeded_dir(tmp_path: Path, agents_text: str, claude_text: str) -> AgentsContext:
    (tmp_path / "AGENTS.md").write_text(agents_text, encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text(claude_text, encoding="utf-8")
    return AgentsContext(project=tmp_path)


@when(parsers.parse('I run "interlocks {subcmd}" there'))
def _run_interlock(ctx: AgentsContext, subcmd: str) -> None:
    ctx.result = run_interlock_in_cwd(ctx.project, *subcmd.split())


@then("the command exits successfully")
def _exit_ok(ctx: AgentsContext) -> None:
    assert ctx.result is not None
    assert ctx.result.returncode == 0, f"stdout={ctx.result.stdout}\nstderr={ctx.result.stderr}"


@then(parsers.parse('the file "{relpath}" exists'))
def _file_exists(ctx: AgentsContext, relpath: str) -> None:
    assert (ctx.project / relpath).is_file()


@then(parsers.parse('the output contains "{needle}"'))
def _output_contains(ctx: AgentsContext, needle: str) -> None:
    assert ctx.result is not None
    combined = ctx.result.stdout + ctx.result.stderr
    assert needle in combined, f"expected {needle!r} in:\n{combined}"


@then(parsers.parse('"{relpath}" contains "{needle}"'))
def _file_contains(ctx: AgentsContext, relpath: str, needle: str) -> None:
    body = (ctx.project / relpath).read_text(encoding="utf-8")
    assert needle in body, f"expected {needle!r} in {relpath}; got:\n{body}"


@then(parsers.parse('"{relpath}" starts with "{prefix}"'))
def _file_starts_with(ctx: AgentsContext, relpath: str, prefix: str) -> None:
    body = (ctx.project / relpath).read_text(encoding="utf-8")
    assert body.startswith(prefix), f"expected {relpath} to start with {prefix!r}; got:\n{body}"


@then(parsers.parse('"{relpath}" equals "{expected}"'))
def _file_equals(ctx: AgentsContext, relpath: str, expected: str) -> None:
    body = (ctx.project / relpath).read_text(encoding="utf-8")
    assert body == expected, f"{relpath} mismatch; got:\n{body!r}"
