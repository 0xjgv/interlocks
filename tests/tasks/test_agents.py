"""Tests for `interlocks agents`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from interlocks.tasks.agents import cmd_agents


def _run_agents(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *args: str,
) -> tuple[int, str, str]:
    from interlocks.config import clear_cache

    monkeypatch.chdir(project)
    clear_cache()
    monkeypatch.setattr(sys, "argv", ["interlocks", "agents", *args])
    returncode = 0
    try:
        cmd_agents()
    except SystemExit as exc:
        returncode = exc.code if isinstance(exc.code, int) else 1
    captured = capsys.readouterr()
    clear_cache()
    return returncode, captured.out, captured.err


def test_agents_json_reports_created_docs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    returncode, stdout, stderr = _run_agents(tmp_path, monkeypatch, capsys, "--json")

    assert returncode == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload == {
        "command": "agents",
        "passed": True,
        "status": "registered",
        "registered": True,
        "files": [
            {"path": "AGENTS.md", "action": "created", "registered": True},
            {"path": "CLAUDE.md", "action": "created", "registered": True},
        ],
        "next_actions": ["Run `interlocks check` after edits."],
    }
    assert "interlocks check" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "interlocks check" in (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")


def test_agents_json_reports_appended_docs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "AGENTS.md").write_text("# Existing", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# Project\n", encoding="utf-8")

    returncode, stdout, stderr = _run_agents(tmp_path, monkeypatch, capsys, "--json")

    assert returncode == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["status"] == "registered"
    assert payload["files"] == [
        {"path": "AGENTS.md", "action": "appended", "registered": True},
        {"path": "CLAUDE.md", "action": "appended", "registered": True},
    ]
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8").startswith("# Existing")


def test_agents_json_reports_kept_docs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "AGENTS.md").write_text("Use interlocks check.\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("Use il check.\n", encoding="utf-8")

    returncode, stdout, stderr = _run_agents(tmp_path, monkeypatch, capsys, "--json")

    assert returncode == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["registered"] is True
    assert payload["files"] == [
        {"path": "AGENTS.md", "action": "kept", "registered": True},
        {"path": "CLAUDE.md", "action": "kept", "registered": True},
    ]
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "Use interlocks check.\n"
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == "Use il check.\n"
