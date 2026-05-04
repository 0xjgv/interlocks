"""Integration tests for `interlocks post-edit` stage."""

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

[tool.interlocks]
src_dir = "app"
"""


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (tmp_path / "app").mkdir()
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@e.co")
    _git(tmp_path, "config", "user.name", "t")
    return tmp_path


def _run_post_edit(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "post-edit"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_post_edit_formats_uncommitted_file(tmp_project: Path) -> None:
    target = tmp_project / "app" / "mod.py"
    target.write_text("x = 0\n", encoding="utf-8")
    _git(tmp_project, "add", "-A")
    _git(tmp_project, "commit", "-q", "-m", "init")
    # stage a modification, then modify again so porcelain status is "MM"
    target.write_text("x=1\n", encoding="utf-8")
    _git(tmp_project, "add", "app/mod.py")
    target.write_text("x=1\ny   =   2\nz=3\n", encoding="utf-8")

    result = _run_post_edit(tmp_project)

    assert result.returncode == 0, result.stderr
    assert target.read_text(encoding="utf-8") == "x = 1\ny = 2\nz = 3\n"


def test_post_edit_noop_when_no_changes(tmp_project: Path) -> None:
    # committed clean file -> no uncommitted changes
    clean = tmp_project / "app" / "clean.py"
    clean.write_text("x = 1\n", encoding="utf-8")
    _git(tmp_project, "add", "-A")
    _git(tmp_project, "commit", "-q", "-m", "init")

    result = _run_post_edit(tmp_project)

    assert result.returncode == 0, result.stderr
    assert clean.read_text(encoding="utf-8") == "x = 1\n"


def test_post_edit_noop_in_process(tmp_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No changed files -> cmd_post_edit returns immediately without running ruff."""
    from interlocks.stages import post_edit as post_edit_mod

    monkeypatch.setattr(post_edit_mod, "changed_py_files", list)
    calls: list[object] = []
    monkeypatch.setattr(post_edit_mod, "run", lambda *a, **k: calls.append(None))

    monkeypatch.chdir(tmp_project)
    post_edit_mod.cmd_post_edit()
    assert calls == []


def test_post_edit_in_process_runs_ruff_on_changed_files(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changed files -> cmd_post_edit dispatches two run() calls (fix + format)."""
    from interlocks.stages import post_edit as post_edit_mod

    monkeypatch.setattr(post_edit_mod, "changed_py_files", lambda: ["app/mod.py"])
    tasks_ran: list[str] = []
    monkeypatch.setattr(post_edit_mod, "run", lambda task, **_: tasks_ran.append(task.description))

    monkeypatch.chdir(tmp_project)
    post_edit_mod.cmd_post_edit()
    assert tasks_ran == ["Fix lint errors", "Format code"]


def test_post_edit_tolerates_unfixable_lint(tmp_project: Path) -> None:
    # file with lint issues ruff can't auto-fix (undefined name) -> no_exit
    target = tmp_project / "app" / "bad.py"
    target.write_text("x = 0\n", encoding="utf-8")
    _git(tmp_project, "add", "-A")
    _git(tmp_project, "commit", "-q", "-m", "init")
    target.write_text("y=undefined_name\n", encoding="utf-8")
    _git(tmp_project, "add", "app/bad.py")
    target.write_text("y=undefined_name\nz=also_undefined\n", encoding="utf-8")

    result = _run_post_edit(tmp_project)

    # no_exit=True: post-edit returns 0 even though ruff reports undefined names
    assert result.returncode == 0, result.stderr
    # ruff format still normalized the spacing
    assert "y = undefined_name" in target.read_text(encoding="utf-8")
