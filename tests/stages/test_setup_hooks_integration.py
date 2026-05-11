"""Integration tests for `interlocks setup-hooks` stage."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import TmpProjectFactory

PYPROJECT = """\
[project]
name = "tmp-proj"
version = "0.0.0"
requires-python = ">=3.11"

[tool.ruff]
target-version = "py311"
"""


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True)


@pytest.fixture
def tmp_project(make_tmp_project: TmpProjectFactory) -> Path:
    root = make_tmp_project(pyproject=PYPROJECT, src_files={}, test_files={})
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@e.co")
    _git(root, "config", "user.name", "t")
    return root


def _run_setup_hooks(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "setup-hooks"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_setup_hooks_installs_pre_commit_and_stop_hook(tmp_project: Path) -> None:
    result = _run_setup_hooks(tmp_project)

    assert result.returncode == 0, result.stderr

    pre_commit = tmp_project / ".git" / "hooks" / "pre-commit"
    assert pre_commit.exists()
    assert os.access(pre_commit, os.X_OK)
    assert "-m interlocks.cli pre-commit" in pre_commit.read_text(encoding="utf-8")

    settings_path = tmp_project / ".claude" / "settings.json"
    assert settings_path.exists()
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    stop = settings["hooks"]["Stop"]
    assert len(stop) == 1
    hooks = stop[0]["hooks"]
    suffix = "-m interlocks.cli post-edit"
    assert any(h["type"] == "command" and h["command"].endswith(suffix) for h in hooks)


def _init_repo_for_worktree(root: Path) -> None:
    """Initialise a git repo with an initial commit (required before adding worktrees)."""
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@e.co")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "placeholder.txt").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _make_worktree_pair(tmp_path: Path, branch: str) -> tuple[Path, Path]:
    """Return (main, linked) after creating a repo and adding a linked worktree."""
    main = tmp_path / "main"
    main.mkdir()
    _init_repo_for_worktree(main)
    linked = tmp_path / "linked"
    subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(linked), "HEAD"],
        cwd=main,
        check=True,
        capture_output=True,
    )
    return main, linked


def test_install_hooks_in_linked_worktree(tmp_path: Path) -> None:
    """install_hooks writes the pre-commit hook to the main repo from a linked worktree."""
    from interlocks.hook_setup import install_hooks

    main, linked = _make_worktree_pair(tmp_path, "feature")
    assert (linked / ".git").is_file(), "linked worktree .git must be a file"

    install_hooks(linked)

    hook = main / ".git" / "hooks" / "pre-commit"
    assert hook.exists()
    assert os.access(hook, os.X_OK)
    assert "-m interlocks.cli pre-commit" in hook.read_text(encoding="utf-8")


def test_pre_commit_hook_installed_detects_linked_worktree(tmp_path: Path) -> None:
    """pre_commit_hook_installed returns True for a hook in the common git dir."""
    from interlocks.hook_setup import install_hooks
    from interlocks.setup_state import pre_commit_hook_installed

    main, linked = _make_worktree_pair(tmp_path, "detect-test")

    install_hooks(linked)

    assert pre_commit_hook_installed(linked)
    assert pre_commit_hook_installed(main)


def test_setup_hooks_is_idempotent(tmp_project: Path) -> None:
    assert _run_setup_hooks(tmp_project).returncode == 0
    assert _run_setup_hooks(tmp_project).returncode == 0

    settings = json.loads((tmp_project / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hooks = settings["hooks"]["Stop"][0]["hooks"]
    post_edit_hooks = [h for h in hooks if h["command"].endswith("-m interlocks.cli post-edit")]
    assert len(post_edit_hooks) == 1
