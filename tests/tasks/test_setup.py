"""Tests for unified `interlocks setup` command."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest


def _write_pyproject(project: Path) -> None:
    (project / "pyproject.toml").write_text(
        '[project]\nname = "probe"\nversion = "0.0.0"\nrequires-python = ">=3.11"\n',
        encoding="utf-8",
    )


def _run_setup(monkeypatch: pytest.MonkeyPatch, project: Path, *args: str) -> None:
    from interlocks.config import clear_cache
    from interlocks.tasks.setup import cmd_setup

    monkeypatch.chdir(project)
    monkeypatch.setattr(sys, "argv", ["interlocks", "setup", *args])
    clear_cache()
    try:
        cmd_setup()
    finally:
        clear_cache()


def test_setup_recommends_check_before_doctor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject(tmp_path)

    _run_setup(monkeypatch, tmp_path)

    out = capsys.readouterr().out
    assert out.index("Run `interlocks check` after edits.") < out.index("Run `interlocks doctor`")


def test_setup_check_fails_when_artifacts_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject(tmp_path)

    with pytest.raises(SystemExit) as exc:
        _run_setup(monkeypatch, tmp_path, "--check")

    out = capsys.readouterr().out
    assert exc.value.code == 1
    assert "missing/stale" in out
    assert "Run `interlocks setup`" in out


def test_setup_installs_hooks_agent_docs_and_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_pyproject(tmp_path)

    _run_setup(monkeypatch, tmp_path)

    pre_commit = tmp_path / ".git" / "hooks" / "pre-commit"
    assert pre_commit.is_file()
    assert os.access(pre_commit, os.X_OK)
    assert "-m interlocks.cli pre-commit" in pre_commit.read_text(encoding="utf-8")

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hooks = settings["hooks"]["Stop"][0]["hooks"]
    assert any(
        hook["type"] == "command" and hook["command"].endswith("-m interlocks.cli post-edit")
        for hook in hooks
    )

    assert "interlocks check" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8").lower()
    assert "interlocks check" in (tmp_path / "CLAUDE.md").read_text(encoding="utf-8").lower()

    from interlocks.defaults_path import path as defaults_path

    installed = tmp_path / ".claude" / "skills" / "interlocks" / "SKILL.md"
    assert installed.read_bytes() == defaults_path("skill/SKILL.md").read_bytes()


def test_setup_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_pyproject(tmp_path)

    _run_setup(monkeypatch, tmp_path)
    first_agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    first_claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    _run_setup(monkeypatch, tmp_path)

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hooks = settings["hooks"]["Stop"][0]["hooks"]
    post_edit_hooks = [
        hook for hook in hooks if hook["command"].endswith("-m interlocks.cli post-edit")
    ]
    assert len(post_edit_hooks) == 1
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == first_agents
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == first_claude


def test_setup_ci_check_reports_missing_when_no_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject(tmp_path)

    with pytest.raises(SystemExit) as exc:
        _run_setup(monkeypatch, tmp_path, "--ci=github", "--check")

    out = capsys.readouterr().out
    assert exc.value.code == 1
    assert "github ci" in out
    assert "missing/stale" in out


def test_setup_ci_installs_github_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject(tmp_path)

    _run_setup(monkeypatch, tmp_path, "--ci=github")

    workflow = tmp_path / ".github" / "workflows" / "interlocks.yml"
    body = workflow.read_text(encoding="utf-8")
    assert "uses: 0xjgv/interlocks@v1" in body
    assert "Installed GitHub Actions workflow" in capsys.readouterr().out

    first = workflow.read_text(encoding="utf-8")
    _run_setup(monkeypatch, tmp_path, "--ci=github")
    assert workflow.read_text(encoding="utf-8") == first

    capsys.readouterr()
    _run_setup(monkeypatch, tmp_path, "--ci=github", "--check")
    assert "missing/stale" not in capsys.readouterr().out


def test_setup_plain_check_does_not_require_ci(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject(tmp_path)
    _run_setup(monkeypatch, tmp_path)
    capsys.readouterr()

    _run_setup(monkeypatch, tmp_path, "--check")

    assert "missing/stale" not in capsys.readouterr().out


def test_setup_check_succeeds_after_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject(tmp_path)

    _run_setup(monkeypatch, tmp_path)
    capsys.readouterr()

    _run_setup(monkeypatch, tmp_path, "--check")

    out = capsys.readouterr().out
    assert "missing/stale" not in out
    assert "Local integrations are installed and current." in out
