"""Integration tests for `harness post-edit` stage."""

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
"""


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True)  # noqa: S607 — git on PATH


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (tmp_path / "harness").mkdir()
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@e.co")
    _git(tmp_path, "config", "user.name", "t")
    return tmp_path


def _run_post_edit(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", "post-edit"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_post_edit_formats_uncommitted_file(tmp_project: Path) -> None:
    target = tmp_project / "harness" / "mod.py"
    target.write_text("x = 0\n", encoding="utf-8")
    _git(tmp_project, "add", "-A")
    _git(tmp_project, "commit", "-q", "-m", "init")
    # stage a modification, then modify again so porcelain status is "MM"
    target.write_text("x=1\n", encoding="utf-8")
    _git(tmp_project, "add", "harness/mod.py")
    target.write_text("x=1\ny   =   2\nz=3\n", encoding="utf-8")

    result = _run_post_edit(tmp_project)

    assert result.returncode == 0, result.stderr
    assert target.read_text(encoding="utf-8") == "x = 1\ny = 2\nz = 3\n"


def test_post_edit_noop_when_no_changes(tmp_project: Path) -> None:
    # committed clean file -> no uncommitted changes
    clean = tmp_project / "harness" / "clean.py"
    clean.write_text("x = 1\n", encoding="utf-8")
    _git(tmp_project, "add", "-A")
    _git(tmp_project, "commit", "-q", "-m", "init")

    result = _run_post_edit(tmp_project)

    assert result.returncode == 0, result.stderr
    assert clean.read_text(encoding="utf-8") == "x = 1\n"


def test_post_edit_tolerates_unfixable_lint(tmp_project: Path) -> None:
    # file with lint issues ruff can't auto-fix (undefined name) -> no_exit
    target = tmp_project / "harness" / "bad.py"
    target.write_text("x = 0\n", encoding="utf-8")
    _git(tmp_project, "add", "-A")
    _git(tmp_project, "commit", "-q", "-m", "init")
    target.write_text("y=undefined_name\n", encoding="utf-8")
    _git(tmp_project, "add", "harness/bad.py")
    target.write_text("y=undefined_name\nz=also_undefined\n", encoding="utf-8")

    result = _run_post_edit(tmp_project)

    # no_exit=True: post-edit returns 0 even though ruff reports undefined names
    assert result.returncode == 0, result.stderr
    # ruff format still normalized the spacing
    assert "y = undefined_name" in target.read_text(encoding="utf-8")
