"""Step defs for tests/features/interlock_greenfield.feature.

Reproduces the spec §1 unblock flow on a synthetic legacy project:
every scenario starts from ``make_legacy_greenfield_project`` and walks
one fix-* (or adoption-status) command through its non-mutating path.

The shared ``greenfield_files_snapshot`` fixture captures the dirty
violation files before the command runs, so the "tree unchanged"
assertion compares byte-for-byte after the command returns.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from tests.step_defs.conftest import (
    interlocks_pythonpath_env,
    make_legacy_greenfield_project,
    make_non_git_project,
    run_interlock_in_cwd,
)

scenarios(str(Path(__file__).parent.parent / "features" / "interlock_greenfield.feature"))


_WATCHED_SOURCES: tuple[str, ...] = ("src/legacy/views.py", "src/legacy/admin.py")


@given(
    "a legacy greenfield project with no quality-gate configuration",
    target_fixture="greenfield_project",
)
def _greenfield_project(tmp_path: Path) -> Path:
    return make_legacy_greenfield_project(tmp_path)


@given(
    "a project directory that is not a git repo",
    target_fixture="non_git_project",
)
def _non_git_project(tmp_path: Path) -> Path:
    return make_non_git_project(tmp_path)


@when(
    parsers.parse('I run "interlocks {subcmd}" in the non-git project'),
    target_fixture="greenfield_result",
)
def _run_in_non_git(non_git_project: Path, subcmd: str) -> subprocess.CompletedProcess[str]:
    return run_interlock_in_cwd(
        non_git_project, *shlex.split(subcmd), env=interlocks_pythonpath_env()
    )


@then("no .git directory was created in the non-git project")
def _no_git_dir(non_git_project: Path) -> None:
    assert not (non_git_project / ".git").exists(), (
        f".git/ was created at {non_git_project / '.git'}"
    )


@when(
    parsers.parse('I run "interlocks {subcmd}" in the greenfield project in default mode'),
    target_fixture="greenfield_result",
)
def _run_in_greenfield_default_mode(
    greenfield_project: Path, subcmd: str
) -> subprocess.CompletedProcess[str]:
    # Not run_interlock_in_cwd: that injects --verbose, which would mask the
    # minimal-default polarity this scenario exists to assert.
    return subprocess.run(
        [sys.executable, "-m", "interlocks.cli", *shlex.split(subcmd)],
        cwd=greenfield_project,
        capture_output=True,
        text=True,
        check=False,
        env=interlocks_pythonpath_env(),
    )


@given("the greenfield project has no virtualenv")
def _no_virtualenv(greenfield_project: Path) -> None:
    """Cold-start state: drop the stubbed .venv and restore the clean baseline.

    The greenfield fixture seeds deliberate lint/format violations to exercise
    the fix-* flows; this scenario isolates the env-skip behavior, so it resets
    the tracked tree to HEAD — leaving an env-less project whose only honest
    ``ci`` finding would be the missing-environment skip.
    """
    venv = greenfield_project / ".venv"
    if venv.is_symlink() or venv.exists():
        venv.unlink()
    subprocess.run(
        ["git", "checkout", "--", "."],
        cwd=greenfield_project,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def greenfield_files_snapshot(greenfield_project: Path) -> dict[str, str]:
    """Byte-for-byte capture of the seeded source files before a command runs."""
    return _snapshot(greenfield_project)


def _snapshot(project: Path) -> dict[str, str]:
    return {rel: (project / rel).read_text(encoding="utf-8") for rel in _WATCHED_SOURCES}


@given(
    parsers.parse('I have run "interlocks {subcmd}" in the greenfield project'),
    target_fixture="prior_result",
)
def _given_run(greenfield_project: Path, subcmd: str) -> subprocess.CompletedProcess[str]:
    return run_interlock_in_cwd(
        greenfield_project, *shlex.split(subcmd), env=interlocks_pythonpath_env()
    )


@when(
    parsers.parse('I run "interlocks {subcmd}" in the greenfield project'),
    target_fixture="greenfield_result",
)
def _run_in_greenfield(
    greenfield_project: Path,
    greenfield_files_snapshot: dict[str, str],
    subcmd: str,
) -> subprocess.CompletedProcess[str]:
    return run_interlock_in_cwd(
        greenfield_project, *shlex.split(subcmd), env=interlocks_pythonpath_env()
    )


@then("the greenfield command exits 0")
def _exits_zero(greenfield_result: subprocess.CompletedProcess[str]) -> None:
    assert greenfield_result.returncode == 0, _detail(greenfield_result)


@then("the greenfield command exits non-zero")
def _exits_nonzero(greenfield_result: subprocess.CompletedProcess[str]) -> None:
    assert greenfield_result.returncode != 0, _detail(greenfield_result)


@then("the greenfield output mentions ruff")
def _mentions_ruff(greenfield_result: subprocess.CompletedProcess[str]) -> None:
    combined = (greenfield_result.stdout + greenfield_result.stderr).lower()
    assert "ruff" in combined, _detail(greenfield_result)


@then(parsers.parse('the greenfield output contains "{needle}"'))
def _output_contains(greenfield_result: subprocess.CompletedProcess[str], needle: str) -> None:
    combined = greenfield_result.stdout + greenfield_result.stderr
    assert needle in combined, f"expected {needle!r} in:\n{combined}"


@then(parsers.parse('the file "{relpath}" exists in the greenfield project'))
def _file_exists(greenfield_project: Path, relpath: str) -> None:
    assert (greenfield_project / relpath).is_file(), f"missing {relpath}"


@then("the seeded source files are unchanged")
def _files_unchanged(greenfield_project: Path, greenfield_files_snapshot: dict[str, str]) -> None:
    for rel, before in greenfield_files_snapshot.items():
        after = (greenfield_project / rel).read_text(encoding="utf-8")
        assert before == after, f"{rel} was mutated:\nbefore:\n{before!r}\nafter:\n{after!r}"


@then("the plan groups candidates by classification")
def _plan_groups(greenfield_project: Path) -> None:
    payload = json.loads(
        (greenfield_project / ".lintfix" / "plan.json").read_text(encoding="utf-8")
    )
    classes = {c["classification"] for c in payload["candidates"]}
    # The seeded project produces I001 (auto), F401 (escrow), UP007 (escrow)
    # at minimum — assert at least two distinct buckets so we know the
    # serializer actually grouped, not just listed.
    assert len(classes) >= 2, f"expected >=2 classifications, got {classes!r}"


@then("the optimize payload exposes selected and not_selected lists")
def _optimize_payload_shape(greenfield_project: Path) -> None:
    payload = json.loads(
        (greenfield_project / ".lintfix" / "optimize.json").read_text(encoding="utf-8")
    )
    assert isinstance(payload.get("selected"), list), payload
    assert isinstance(payload.get("not_selected"), list), payload


@then("the metrics payload exposes a sources truthtable")
def _metrics_payload_sources(greenfield_project: Path) -> None:
    payload = json.loads(
        (greenfield_project / ".lintfix" / "metrics.json").read_text(encoding="utf-8")
    )
    sources = payload.get("sources")
    assert isinstance(sources, dict), payload
    assert set(sources.keys()) >= {"plan", "optimize", "replay"}, sources


@then("the greenfield output names at least one missing adoption artifact")
def _doctor_names_gap(greenfield_result: subprocess.CompletedProcess[str]) -> None:
    combined = greenfield_result.stdout + greenfield_result.stderr
    needles = ("[git hook]", "[claude hook]", "[agent docs]", "[ci workflow]", "[claude skill]")
    assert any(n in combined for n in needles), (
        f"expected one of {needles!r} in doctor output; got:\n{combined}"
    )


@then("the greenfield output names at least one missing adoption gap inline")
def _doctor_names_gap_inline(greenfield_result: subprocess.CompletedProcess[str]) -> None:
    """Default-mode doctor must print the gap detail, not just `ready (N gap)`.

    The greenfield project has no preset, no [tool.interlocks] block, no git/claude
    hooks, no CI workflow, and no acceptance scaffold — so at least one `warn`-row
    gap line is emitted by the default render's `_print_capped(_gap_lines(...))`.
    """
    combined = greenfield_result.stdout + greenfield_result.stderr
    needles = (
        "ci workflow: run `interlocks setup --ci=github`",
        "preset: run `interlocks presets set progressive`",
        "interlocks cfg: defaults apply",
        "acceptance: not wired",
        "run `interlocks setup`",
    )
    assert any(n in combined for n in needles), (
        f"expected an inline gap line (one of {needles!r}) in default-mode doctor "
        f"output; got:\n{combined}"
    )


@then(parsers.parse('the greenfield output does not contain "{needle}"'))
def _output_not_contains(greenfield_result: subprocess.CompletedProcess[str], needle: str) -> None:
    combined = greenfield_result.stdout + greenfield_result.stderr
    assert needle not in combined, f"expected {needle!r} absent, but found it in:\n{combined}"


def _detail(result: subprocess.CompletedProcess[str]) -> str:
    return f"exit={result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
