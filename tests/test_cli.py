"""Unit tests for harness.cli dispatcher."""

from __future__ import annotations

import sys

import pytest

from harness.cli import TASK_GROUPS, TASKS, cmd_help, main


def test_tasks_dict_built_from_groups() -> None:
    expected = {name for _, group in TASK_GROUPS for name in group}
    assert set(TASKS.keys()) == expected
    # Each entry is (callable, description).
    for fn, desc in TASKS.values():
        assert callable(fn)
        assert isinstance(desc, str) and desc


def test_cmd_help_prints_usage_and_groups(capsys: pytest.CaptureFixture[str]) -> None:
    cmd_help()
    out = capsys.readouterr().out
    assert "Usage: harness <command>" in out
    assert "Tasks:" in out
    assert "Stages:" in out
    assert "help" in out  # known command listed


def test_main_no_args_prints_help(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["harness"])
    main()
    out = capsys.readouterr().out
    assert "Usage: harness <command>" in out


def test_main_unknown_command_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["harness", "nope"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Unknown command: nope" in captured.err
    assert "Usage: harness <command>" in captured.out


def test_main_dispatches_known_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["harness", "help"])
    main()  # cmd_help() is safe to run
    assert "Usage: harness <command>" in capsys.readouterr().out


def test_main_skips_flag_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flags (starting with -) are filtered out before dispatch."""
    calls: list[str] = []

    def fake() -> None:
        calls.append("ran")

    monkeypatch.setitem(TASKS, "help", (fake, "Show help"))
    monkeypatch.setattr(sys, "argv", ["harness", "--verbose", "help"])
    main()
    assert calls == ["ran"]
