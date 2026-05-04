"""Integration tests for `interlocks pre-commit` stage."""

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
    subprocess.run(["git", *args], cwd=cwd, check=True)


def _git_capture(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    # interlocks/ exists but without __init__.py so it doesn't shadow the installed pkg
    (tmp_path / "interlocks").mkdir()
    (tmp_path / "tests").mkdir()
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@e.co")
    _git(tmp_path, "config", "user.name", "t")
    return tmp_path


def _run_pre_commit(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "pre-commit"],
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


def test_pre_commit_noop_in_process(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from interlocks.stages import pre_commit as pre_commit_mod

    monkeypatch.setattr(pre_commit_mod, "staged_py_files", list)
    pre_commit_mod.cmd_pre_commit()
    assert "No staged Python files" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("staged", "expected_task_descs"),
    [
        (["interlocks/mod.py"], ["Type check", "Run tests"]),
        (["tests/test_x.py"], ["Type check"]),
    ],
    ids=["src-runs-tests", "non-src-skips-tests"],
)
def test_pre_commit_in_process_dispatches(
    monkeypatch: pytest.MonkeyPatch,
    staged: list[str],
    expected_task_descs: list[str],
) -> None:
    from interlocks.stages import pre_commit as pre_commit_mod

    calls: list[object] = []
    monkeypatch.setattr(pre_commit_mod, "staged_py_files", lambda: staged)
    monkeypatch.setattr(pre_commit_mod, "cmd_fix", lambda files: calls.append(("fix", files)))
    monkeypatch.setattr(
        pre_commit_mod, "cmd_format", lambda files: calls.append(("format", files))
    )
    monkeypatch.setattr(pre_commit_mod, "stage", lambda files: calls.append(("stage", files)))
    monkeypatch.setattr(
        pre_commit_mod,
        "run_tasks",
        lambda tasks: calls.append(("run_tasks", [t.description for t in tasks])),
    )

    pre_commit_mod.cmd_pre_commit()
    assert calls == [
        ("fix", staged),
        ("format", staged),
        ("stage", staged),
        ("run_tasks", expected_task_descs),
    ]
