"""Integration tests for `harness setup-hooks` stage."""

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
requires-python = ">=3.13"

[tool.ruff]
target-version = "py313"
"""


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True)  # noqa: S607 — git on PATH


@pytest.fixture
def tmp_project(make_tmp_project: TmpProjectFactory) -> Path:
    root = make_tmp_project(pyproject=PYPROJECT, src_files={}, test_files={})
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@e.co")
    _git(root, "config", "user.name", "t")
    return root


def _run_setup_hooks(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", "setup-hooks"],
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
    assert "-m harness.cli pre-commit" in pre_commit.read_text(encoding="utf-8")

    settings_path = tmp_project / ".claude" / "settings.json"
    assert settings_path.exists()
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    stop = settings["hooks"]["Stop"]
    assert len(stop) == 1
    hooks = stop[0]["hooks"]
    assert any(
        h["type"] == "command" and h["command"].endswith("-m harness.cli post-edit") for h in hooks
    )


def test_setup_hooks_is_idempotent(tmp_project: Path) -> None:
    assert _run_setup_hooks(tmp_project).returncode == 0
    assert _run_setup_hooks(tmp_project).returncode == 0

    settings = json.loads((tmp_project / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hooks = settings["hooks"]["Stop"][0]["hooks"]
    post_edit_hooks = [h for h in hooks if h["command"].endswith("-m harness.cli post-edit")]
    assert len(post_edit_hooks) == 1
