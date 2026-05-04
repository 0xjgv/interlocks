"""Tests for interlocks.git — ref-scoped diff helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from interlocks import git as git_mod
from interlocks.git import changed_py_files_vs


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


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
        '[tool.interlocks]\nsrc_dir = "interlocks"\ntest_dir = "tests"\n',
        encoding="utf-8",
    )
    (tmp_path / "interlocks").mkdir()
    (tmp_path / "interlocks" / "base.py").write_text("x = 1\n", encoding="utf-8")
    _commit_all(tmp_path, "base")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_changed_py_files_vs_happy_path(repo: Path) -> None:
    (repo / "interlocks" / "added.py").write_text("y = 2\n", encoding="utf-8")
    _commit_all(repo, "add file")

    assert changed_py_files_vs("HEAD~1") == {"interlocks/added.py"}


def test_changed_py_files_vs_ignores_non_py(repo: Path) -> None:
    (repo / "interlocks" / "added.py").write_text("y = 2\n", encoding="utf-8")
    (repo / "interlocks" / "notes.md").write_text("hi\n", encoding="utf-8")
    (repo / "interlocks" / "data.txt").write_text("x\n", encoding="utf-8")
    _commit_all(repo, "mixed")

    assert changed_py_files_vs("HEAD~1") == {"interlocks/added.py"}


def test_changed_py_files_vs_filters_out_of_tree_paths(repo: Path) -> None:
    """Files outside the configured src/test dirs are dropped (matches siblings)."""
    (repo / "interlocks" / "in_src.py").write_text("a = 1\n", encoding="utf-8")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "helper.py").write_text("b = 2\n", encoding="utf-8")
    _commit_all(repo, "mixed dirs")

    assert changed_py_files_vs("HEAD~1") == {"interlocks/in_src.py"}


def test_changed_py_files_vs_detects_renames(repo: Path) -> None:
    body = "def greet():\n    return 'hi there'\n" * 5
    (repo / "interlocks" / "old_name.py").write_text(body, encoding="utf-8")
    _commit_all(repo, "seed file")
    _git("mv", "interlocks/old_name.py", "interlocks/new_name.py", cwd=repo)
    _commit_all(repo, "rename")

    result = changed_py_files_vs("HEAD~1")
    assert result == {"interlocks/new_name.py"}


def test_changed_py_files_vs_missing_ref_returns_empty(repo: Path) -> None:
    assert changed_py_files_vs("does-not-exist") == set()


def test_changed_py_files_vs_includes_unstaged(repo: Path) -> None:
    """Uncommitted edits to a tracked file surface vs the same ref."""
    (repo / "interlocks" / "base.py").write_text("x = 2\n", encoding="utf-8")

    assert changed_py_files_vs("HEAD") == {"interlocks/base.py"}


def test_changed_py_files_vs_includes_staged(repo: Path) -> None:
    """Staged-but-uncommitted additions surface vs the same ref."""
    (repo / "interlocks" / "added.py").write_text("y = 2\n", encoding="utf-8")
    _git("add", "interlocks/added.py", cwd=repo)

    assert changed_py_files_vs("HEAD") == {"interlocks/added.py"}


def test_changed_py_files_vs_includes_untracked(repo: Path) -> None:
    """Untracked .py files under src/test dirs surface vs the same ref."""
    (repo / "interlocks" / "new.py").write_text("z = 3\n", encoding="utf-8")

    assert changed_py_files_vs("HEAD") == {"interlocks/new.py"}


def test_changed_py_files_vs_ignores_ref_advancing_past_head(repo: Path) -> None:
    """Commits on the ref after branch-off don't leak in (merge-base scoping)."""
    _git("checkout", "-q", "-b", "feature", cwd=repo)
    _git("checkout", "-q", "main", cwd=repo)
    (repo / "interlocks" / "on_main.py").write_text("m = 1\n", encoding="utf-8")
    _commit_all(repo, "advance main")
    _git("checkout", "-q", "feature", cwd=repo)

    assert changed_py_files_vs("main") == set()


def test_changed_py_files_vs_main_wrapper(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Wrapper delegates to changed_py_files_vs('origin/main')."""
    calls: list[str] = []

    def _fake(ref: str) -> set[str]:
        calls.append(ref)
        return {"sentinel.py"}

    monkeypatch.setattr(git_mod, "changed_py_files_vs", _fake)

    assert git_mod.changed_py_files_vs_main() == {"sentinel.py"}
    assert calls == ["origin/main"]


def _stub_cfg(monkeypatch: pytest.MonkeyPatch, src: str, test: str) -> None:
    stub = SimpleNamespace(src_dir_arg=src, test_dir_arg=test)
    monkeypatch.setattr(git_mod, "load_config", lambda: stub)


def test_src_test_prefixes_includes_both(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_cfg(monkeypatch, "src", "tests")
    assert git_mod._src_test_prefixes() == ("src/", "tests/")


def test_src_test_prefixes_skips_dot_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """Project root (`.`) is not a prefix — fall through to the `("",)` sentinel."""
    _stub_cfg(monkeypatch, ".", ".")
    assert git_mod._src_test_prefixes() == ("",)


def test_src_test_prefixes_skips_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty src/test dirs are skipped — fall through to the `("",)` sentinel."""
    _stub_cfg(monkeypatch, "", "")
    assert git_mod._src_test_prefixes() == ("",)


def test_src_test_prefixes_flat_src_matches_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flat layout: ``src=.`` means the project root is src — every ``.py`` qualifies.

    Previously the `.` was dropped and only ``test_dir`` survived, filtering top-level
    files out of ``--changed`` scope. Bug surfaced when running ``check --changed`` in
    a partially-adopted repo: source edits weren't picked up.
    """
    _stub_cfg(monkeypatch, ".", "tests")
    assert git_mod._src_test_prefixes() == ("",)


def test_src_test_prefixes_flat_test_matches_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mirror of the flat-src case: ``test=.`` covers the whole project."""
    _stub_cfg(monkeypatch, "src", ".")
    assert git_mod._src_test_prefixes() == ("",)


def test_src_test_prefixes_empty_src_with_tests_matches_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty src with a configured test dir still matches everything (no narrowing)."""
    _stub_cfg(monkeypatch, "", "tests")
    assert git_mod._src_test_prefixes() == ("",)
