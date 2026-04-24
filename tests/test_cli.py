"""Unit tests for harness.cli dispatcher."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

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


def test_cmd_help_prints_active_preset_and_resolved_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [project]
            name = "pkg"
            version = "0.0.0"

            [tool.harness]
            preset = "strict"
            coverage_min = 91
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    from harness.config import clear_cache

    clear_cache()
    try:
        cmd_help()
    finally:
        clear_cache()

    out = capsys.readouterr().out
    import re

    def _row(key: str, value: str) -> re.Pattern[str]:
        return re.compile(rf"^\s*{re.escape(key)}\s+{re.escape(value)}\s*$", re.MULTILINE)

    assert _row("preset", "strict").search(out), out
    assert _row("coverage_min", "91").search(out), out
    assert _row("run_mutation_in_ci", "True").search(out), out


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
