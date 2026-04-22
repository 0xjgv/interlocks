"""Integration + unit tests for `harness acceptance`."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "acc-probe"
    version = "0.0.0"
    requires-python = ">=3.13"
    """
)

_PASSING_FEATURE = textwrap.dedent(
    """\
    Feature: Math sanity
      Scenario: Two plus three
        Given the number 2
        When I add 3
        Then the result is 5
    """
)

_FAILING_FEATURE = textwrap.dedent(
    """\
    Feature: Math sanity
      Scenario: Broken addition
        Given the number 2
        When I add 3
        Then the result is 99
    """
)

_STEP_DEFS = textwrap.dedent(
    """\
    from pytest_bdd import given, parsers, scenarios, then, when

    scenarios("../features/example.feature")


    @given(parsers.parse("the number {value:d}"), target_fixture="value")
    def _value(value):
        return value


    @when(parsers.parse("I add {addend:d}"), target_fixture="result")
    def _add(value, addend):
        return value + addend


    @then(parsers.parse("the result is {expected:d}"))
    def _check(result, expected):
        assert result == expected
    """
)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    return tmp_path


def _run_cli(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )


def test_acceptance_noop_without_features(tmp_project: Path) -> None:
    """Empty foreign project: exit 0 + skip nudge, never a crash."""
    result = _run_cli(tmp_project, "acceptance")
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "acceptance:" in result.stdout


def _scaffold_feature(project: Path, feature_body: str) -> None:
    (project / "tests" / "features").mkdir(parents=True)
    (project / "tests" / "features" / "example.feature").write_text(feature_body, encoding="utf-8")
    (project / "tests" / "step_defs").mkdir()
    (project / "tests" / "step_defs" / "test_example.py").write_text(_STEP_DEFS, encoding="utf-8")


@pytest.mark.slow
def test_acceptance_passes_on_valid_scenario(tmp_project: Path) -> None:
    _scaffold_feature(tmp_project, _PASSING_FEATURE)
    result = _run_cli(tmp_project, "acceptance")
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "Acceptance (pytest-bdd)" in result.stdout


@pytest.mark.slow
def test_acceptance_fails_on_broken_scenario(tmp_project: Path) -> None:
    _scaffold_feature(tmp_project, _FAILING_FEATURE)
    result = _run_cli(tmp_project, "acceptance")
    assert result.returncode != 0


def test_task_acceptance_returns_none_without_features(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from harness.config import clear_cache
    from harness.tasks import acceptance as mod

    monkeypatch.chdir(tmp_project)
    clear_cache()
    assert mod.task_acceptance() is None


def test_task_acceptance_pytest_bdd_allows_rc_5(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pytest exits 5 when it collects nothing — must be treated as pass."""
    from harness.config import clear_cache
    from harness.tasks import acceptance as mod

    (tmp_project / "tests" / "features").mkdir(parents=True)  # empty features dir
    monkeypatch.chdir(tmp_project)
    clear_cache()
    task = mod.task_acceptance()
    assert task is not None
    assert task.description == "Acceptance (pytest-bdd)"
    assert 5 in task.allowed_rcs


def test_task_acceptance_off_override_skips(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from harness.config import clear_cache
    from harness.tasks import acceptance as mod

    (tmp_project / "tests" / "features").mkdir(parents=True)
    (tmp_project / "pyproject.toml").write_text(
        _PYPROJECT + '\n[tool.harness]\nacceptance_runner = "off"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_project)
    clear_cache()
    assert mod.task_acceptance() is None


def test_task_acceptance_behave_branch(tmp_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from harness.config import clear_cache
    from harness.tasks import acceptance as mod

    features = tmp_project / "features"
    (features / "steps").mkdir(parents=True)
    (features / "environment.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    clear_cache()
    task = mod.task_acceptance()
    assert task is not None
    assert task.description == "Acceptance (behave)"
    assert "behave" in task.cmd
