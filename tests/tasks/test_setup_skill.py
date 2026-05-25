"""Tests for `interlocks setup-skill`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from interlocks.defaults_path import path as defaults_path
from interlocks.setup_state import SKILL_DEST
from interlocks.tasks.setup_skill import _render_skill_status, cmd_setup_skill


def _run_setup_skill(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *args: str,
) -> tuple[int, str, str]:
    from interlocks.config import clear_cache

    monkeypatch.chdir(project)
    clear_cache()
    monkeypatch.setattr(sys, "argv", ["interlocks", "setup-skill", *args])
    returncode = 0
    try:
        cmd_setup_skill()
    except SystemExit as exc:
        returncode = exc.code if isinstance(exc.code, int) else 1
    captured = capsys.readouterr()
    clear_cache()
    return returncode, captured.out, captured.err


def test_setup_skill_json_reports_installed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    returncode, stdout, stderr = _run_setup_skill(tmp_path, monkeypatch, capsys, "--json")

    assert returncode == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload == {
        "command": "setup-skill",
        "passed": True,
        "status": "installed",
        "installed": True,
        "path": ".claude/skills/interlocks/SKILL.md",
        "action": "installed",
        "next_actions": ["Use the installed Claude skill when working in this repo."],
    }
    installed = tmp_path / SKILL_DEST
    assert installed.read_bytes() == defaults_path("skill/SKILL.md").read_bytes()


def test_setup_skill_json_reports_kept(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    installed = tmp_path / SKILL_DEST
    installed.parent.mkdir(parents=True)
    installed.write_bytes(defaults_path("skill/SKILL.md").read_bytes())

    returncode, stdout, stderr = _run_setup_skill(tmp_path, monkeypatch, capsys, "--json")

    assert returncode == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["status"] == "installed"
    assert payload["installed"] is True
    assert payload["path"] == ".claude/skills/interlocks/SKILL.md"
    assert payload["action"] == "kept"


def test_setup_skill_json_reports_updated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    installed = tmp_path / SKILL_DEST
    installed.parent.mkdir(parents=True)
    installed.write_text("old skill\n", encoding="utf-8")

    returncode, stdout, stderr = _run_setup_skill(tmp_path, monkeypatch, capsys, "--json")

    assert returncode == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["status"] == "installed"
    assert payload["installed"] is True
    assert payload["path"] == ".claude/skills/interlocks/SKILL.md"
    assert payload["action"] == "updated"
    assert installed.read_bytes() == defaults_path("skill/SKILL.md").read_bytes()


def test_setup_skill_human_status_still_renders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    returncode, stdout, stderr = _run_setup_skill(tmp_path, monkeypatch, capsys)

    assert returncode == 0
    assert stderr == ""
    assert "[claude skill]" in stdout
    assert "installed" in stdout


def test_render_skill_status_reports_detector_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows: list[tuple[str, str, str, str, bool]] = []

    def fake_row(
        label: str,
        target: str,
        status: str,
        *,
        state: str,
        force: bool,
    ) -> None:
        rows.append((label, target, status, state, force))

    monkeypatch.setattr("interlocks.tasks.setup_skill.skill_installed", lambda root: False)
    monkeypatch.setattr("interlocks.tasks.setup_skill.ui.row", fake_row)

    _render_skill_status(tmp_path)

    assert rows == [
        (
            "claude skill",
            ".claude/skills/interlocks/SKILL.md",
            "missing/stale",
            "fail",
            True,
        )
    ]


def test_render_skill_status_reports_installed_detector_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows: list[tuple[str, str, str, str, bool]] = []

    def fake_row(
        label: str,
        target: str,
        status: str,
        *,
        state: str,
        force: bool,
    ) -> None:
        rows.append((label, target, status, state, force))

    monkeypatch.setattr("interlocks.tasks.setup_skill.skill_installed", lambda root: True)
    monkeypatch.setattr("interlocks.tasks.setup_skill.ui.row", fake_row)

    _render_skill_status(tmp_path)

    assert rows == [
        (
            "claude skill",
            ".claude/skills/interlocks/SKILL.md",
            "installed",
            "ok",
            True,
        )
    ]
