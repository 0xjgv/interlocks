"""Tests for harness.git — ref-scoped diff helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness import git as git_mod
from harness.git import changed_py_files_vs


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)  # noqa: S607 — git on PATH


def _init_repo(root: Path) -> None:
    _git("init", "-q", "-b", "main", cwd=root)
    _git("config", "user.email", "test@example.com", cwd=root)
    _git("config", "user.name", "Test", cwd=root)
    _git("config", "commit.gpgsign", "false", cwd=root)
    _git("config", "core.hooksPath", "/dev/null", cwd=root)


def _commit_all(root: Path, message: str) -> None:
    _git("add", "-A", cwd=root)
    _git("commit", "-q", "-m", message, cwd=root)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _init_repo(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.harness]\nsrc_dir = "harness"\ntest_dir = "tests"\n',
        encoding="utf-8",
    )
    (tmp_path / "harness").mkdir()
    (tmp_path / "harness" / "base.py").write_text("x = 1\n", encoding="utf-8")
    _commit_all(tmp_path, "base")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_changed_py_files_vs_happy_path(repo: Path) -> None:
    (repo / "harness" / "added.py").write_text("y = 2\n", encoding="utf-8")
    _commit_all(repo, "add file")

    assert changed_py_files_vs("HEAD~1") == {"harness/added.py"}


def test_changed_py_files_vs_ignores_non_py(repo: Path) -> None:
    (repo / "harness" / "added.py").write_text("y = 2\n", encoding="utf-8")
    (repo / "harness" / "notes.md").write_text("hi\n", encoding="utf-8")
    (repo / "harness" / "data.txt").write_text("x\n", encoding="utf-8")
    _commit_all(repo, "mixed")

    assert changed_py_files_vs("HEAD~1") == {"harness/added.py"}


def test_changed_py_files_vs_filters_out_of_tree_paths(repo: Path) -> None:
    """Files outside the configured src/test dirs are dropped (matches siblings)."""
    (repo / "harness" / "in_src.py").write_text("a = 1\n", encoding="utf-8")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "helper.py").write_text("b = 2\n", encoding="utf-8")
    _commit_all(repo, "mixed dirs")

    assert changed_py_files_vs("HEAD~1") == {"harness/in_src.py"}


def test_changed_py_files_vs_detects_renames(repo: Path) -> None:
    body = "def greet():\n    return 'hi there'\n" * 5
    (repo / "harness" / "old_name.py").write_text(body, encoding="utf-8")
    _commit_all(repo, "seed file")
    _git("mv", "harness/old_name.py", "harness/new_name.py", cwd=repo)
    _commit_all(repo, "rename")

    result = changed_py_files_vs("HEAD~1")
    assert result == {"harness/new_name.py"}


def test_changed_py_files_vs_missing_ref_returns_empty(repo: Path) -> None:
    assert changed_py_files_vs("does-not-exist") == set()


def test_changed_py_files_vs_main_wrapper(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Wrapper delegates to changed_py_files_vs('origin/main')."""
    calls: list[str] = []

    def _fake(ref: str) -> set[str]:
        calls.append(ref)
        return {"sentinel.py"}

    monkeypatch.setattr(git_mod, "changed_py_files_vs", _fake)

    assert git_mod.changed_py_files_vs_main() == {"sentinel.py"}
    assert calls == ["origin/main"]
