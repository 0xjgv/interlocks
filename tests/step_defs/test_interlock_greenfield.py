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
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from tests.step_defs.conftest import (
    interlocks_pythonpath_env,
    make_legacy_greenfield_project,
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


def _detail(result: subprocess.CompletedProcess[str]) -> str:
    return f"exit={result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
