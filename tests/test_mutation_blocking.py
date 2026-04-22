"""Mutation enforcement: `enforce_mutation` + `mutation_min_score` gate the exit code."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_MODULE_SRC = textwrap.dedent(
    """\
    def is_positive(x):
        return x > 0
    """
)

_TEST_SRC = textwrap.dedent(
    """\
    import unittest
    from mypkg.mod import is_positive

    class TestIsPositive(unittest.TestCase):
        def test_positive(self):
            self.assertTrue(is_positive(1))
    """
)

_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "mut-enforce"
    version = "0.0.1"
    requires-python = ">=3.13"

    [tool.coverage.run]
    source = ["mypkg"]
    branch = true

    [tool.mutmut]
    paths_to_mutate = ["mypkg/"]
    tests_dir = ["tests/"]
    """
)


def _run_coverage(cwd: Path) -> None:
    cmd = [sys.executable, "-m", "coverage", "run", "-m", "unittest", "discover", "-s", "tests"]
    subprocess.run(cmd, cwd=cwd, check=True)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(_MODULE_SRC, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "test_mod.py").write_text(_TEST_SRC, encoding="utf-8")
    return tmp_path


def _write_pyproject(project: Path, *, enforce: bool, min_score: float = 99.0) -> None:
    (project / "pyproject.toml").write_text(
        _PYPROJECT
        + "\n[tool.harness]\n"
        + "mutation_min_coverage = 0\n"
        + f"mutation_min_score = {min_score}\n"
        + f"enforce_mutation = {str(enforce).lower()}\n",
        encoding="utf-8",
    )


@pytest.mark.slow
def test_mutation_exits_when_enforced_and_below_threshold(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """min_score = 99.0 with surviving mutants → SystemExit(1)."""
    _write_pyproject(tmp_project, enforce=True, min_score=99.0)
    monkeypatch.chdir(tmp_project)
    monkeypatch.syspath_prepend(str(tmp_project))
    _run_coverage(tmp_project)
    monkeypatch.setattr(sys, "argv", ["harness", "mutation", "--max-runtime=30"])

    from harness.tasks.mutation import cmd_mutation

    with pytest.raises(SystemExit) as excinfo:
        cmd_mutation()
    assert excinfo.value.code == 1

    captured = capsys.readouterr()
    assert "Mutation: score" in captured.out
    assert "below threshold" in captured.out


@pytest.mark.slow
def test_mutation_stays_advisory_when_not_enforced(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Same fixture + enforce_mutation=false → no SystemExit even with low kill ratio."""
    _write_pyproject(tmp_project, enforce=False, min_score=99.0)
    monkeypatch.chdir(tmp_project)
    monkeypatch.syspath_prepend(str(tmp_project))
    _run_coverage(tmp_project)
    monkeypatch.setattr(sys, "argv", ["harness", "mutation", "--max-runtime=30"])

    from harness.tasks.mutation import cmd_mutation

    cmd_mutation()  # must not raise

    captured = capsys.readouterr()
    assert "Mutation: score" in captured.out
