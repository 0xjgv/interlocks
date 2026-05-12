"""Diff plumbing: base resolution, changed files, post-image hunk parsing."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from interlocks.lintfix.diff import changed_files, changed_hunks, resolve_base


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_repo(root: Path) -> None:
    _git("init", "-q", "-b", "main", cwd=root)
    _git("config", "user.email", "test@example.com", cwd=root)
    _git("config", "user.name", "Test", cwd=root)
    _git("config", "commit.gpgsign", "false", cwd=root)
    _git("config", "core.hooksPath", "/dev/null", cwd=root)


def _commit(root: Path, msg: str) -> None:
    _git("add", "-A", cwd=root)
    _git("commit", "-q", "-m", msg, cwd=root)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _init_repo(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.interlocks]\nsrc_dir = "."\ntest_dir = "tests"\n', encoding="utf-8"
    )
    (tmp_path / "base.py").write_text("x = 1\n" * 5, encoding="utf-8")
    _commit(tmp_path, "base")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_resolve_base_returns_sha(repo: Path) -> None:
    sha = resolve_base("HEAD")
    assert sha
    assert len(sha) >= 7


def test_resolve_base_empty_for_unknown_ref(repo: Path) -> None:
    assert resolve_base("does-not-exist") == ""


def test_changed_files_picks_up_new_and_modified(repo: Path) -> None:
    (repo / "added.py").write_text("a = 1\n", encoding="utf-8")
    (repo / "base.py").write_text("x = 2\n" * 5, encoding="utf-8")
    base = resolve_base("HEAD")

    result = changed_files(base)
    assert "added.py" in result
    assert "base.py" in result


def test_changed_files_skips_non_py(repo: Path) -> None:
    (repo / "notes.md").write_text("hi\n", encoding="utf-8")
    base = resolve_base("HEAD")
    assert "notes.md" not in changed_files(base)


def test_changed_hunks_parses_post_image_lines(repo: Path) -> None:
    # Modify lines 2-3 of base.py — git records the new range.
    lines = ["x = 1\n", "x = 1\n", "y = 2\n", "z = 3\n", "x = 1\n"]
    (repo / "base.py").write_text("".join(lines), encoding="utf-8")
    base = resolve_base("HEAD")
    parsed = changed_hunks(base, ("base.py",))
    fh = parsed["base.py"]
    assert any(h.contains(2) or h.contains(3) or h.contains(4) for h in fh.hunks)
    assert not fh.contains(1)


def test_changed_hunks_treats_untracked_as_full_file(repo: Path) -> None:
    (repo / "new.py").write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    base = resolve_base("HEAD")
    parsed = changed_hunks(base, ("new.py",))
    fh = parsed["new.py"]
    assert fh.contains(1)
    assert fh.contains(3)


def test_changed_files_empty_when_base_unknown() -> None:
    assert changed_files("") == ()
