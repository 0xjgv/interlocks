"""Integration tests for `harness pre-commit` stage."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PYPROJECT = """\
[project]
name = "tmp-proj"
version = "0.0.0"
requires-python = ">=3.13"

[tool.ruff]
target-version = "py313"
line-length = 99

[tool.basedpyright]
pythonVersion = "3.13"
typeCheckingMode = "standard"
"""


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True)  # noqa: S607 — git on PATH


def _git_capture(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)  # noqa: S607 — git on PATH
    return result.stdout


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    # harness/ exists but without __init__.py so it doesn't shadow the installed pkg
    (tmp_path / "harness").mkdir()
    (tmp_path / "tests").mkdir()
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@e.co")
    _git(tmp_path, "config", "user.name", "t")
    return tmp_path


def _run_pre_commit(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", "pre-commit"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_pre_commit_fixes_and_restages_staged_file(tmp_project: Path) -> None:
    target = tmp_project / "tests" / "test_a.py"
    target.write_text("x=1\ny   =   2\n", encoding="utf-8")
    _git(tmp_project, "add", "tests/test_a.py")

    result = _run_pre_commit(tmp_project)

    assert result.returncode == 0, result.stdout + result.stderr
    # The working-tree file was formatted in place
    assert target.read_text(encoding="utf-8") == "x = 1\ny = 2\n"
    # And the fixed content was re-staged (index matches working tree)
    diff = _git_capture(tmp_project, "diff", "--cached", "tests/test_a.py")
    assert "x = 1" in diff
    assert "y = 2" in diff


def test_pre_commit_noop_when_nothing_staged(tmp_project: Path) -> None:
    result = _run_pre_commit(tmp_project)

    assert result.returncode == 0, result.stderr
    assert "No staged Python files" in result.stdout
