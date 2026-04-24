"""Unit tests for harness.cli dispatcher."""

from __future__ import annotations

import re
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest

from harness.cli import TASK_GROUPS, TASKS, cmd_help, cmd_presets, main
from harness.config import clear_cache


@pytest.fixture
def clean_config_cache() -> Iterator[None]:
    clear_cache()
    try:
        yield
    finally:
        clear_cache()


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
    assert "pyharness v" in out
    assert "command=help" in out
    assert "Usage: harness <command>" in out
    assert "── Usage" in out
    assert "── Commands" in out
    assert "Tasks:" in out
    assert "Stages:" in out
    assert "[help]" in out  # known command listed with bracket tag
    assert "[fix]" in out
    assert "[check]" in out


def test_cmd_help_prints_active_preset_and_resolved_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
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

    cmd_help()

    out = capsys.readouterr().out

    def _row(key: str, value: str) -> re.Pattern[str]:
        return re.compile(rf"^\s*{re.escape(key)}\s+{re.escape(value)}\s*$", re.MULTILINE)

    assert _row("preset", "strict").search(out), out
    assert _row("coverage_min", "91").search(out), out
    assert _row("run_mutation_in_ci", "True").search(out), out


def test_cmd_presets_prints_options_and_copyable_config(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cmd_presets()
    out = capsys.readouterr().out
    assert "pyharness v" in out
    assert "command=presets" in out
    assert "── Current" in out
    assert "── Current Values" in out
    assert "coverage_min" in out
    assert "mutation_ci_mode" in out
    assert "── Available Presets" in out
    assert "baseline" in out
    assert "strict" in out
    assert "legacy" in out
    assert "── Next Steps" in out
    assert "Set a project preset with the CLI:" in out
    assert "harness presets set baseline" in out
    assert "Or add this to pyproject.toml:" in out
    assert '[tool.harness]\n    preset = "baseline"' in out
    assert "manually override any threshold" in out
    assert "pyproject.toml" in out


def test_cmd_presets_prints_active_preset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
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
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    cmd_presets()

    out = capsys.readouterr().out
    assert re.search(r"^\s*preset\s+strict\s*$", out, re.MULTILINE), out
    assert re.search(r"^\s*coverage_min\s+90 \(preset-derived\)\s*$", out, re.MULTILINE), out
    assert re.search(r"^\s*run_mutation_in_ci\s+True \(preset-derived\)\s*$", out, re.MULTILINE), (
        out
    )


def test_cmd_presets_set_appends_harness_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "pkg"\nversion = "0.0.0"\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["harness", "presets", "set", "baseline"])

    cmd_presets()

    assert '[tool.harness]\npreset = "baseline"\n' in (tmp_path / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert "set [tool.harness] preset = 'baseline'" in capsys.readouterr().out


def test_cmd_presets_set_replaces_existing_preset_without_thresholds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_config_cache: None
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [project]
            name = "pkg"
            version = "0.0.0"

            [tool.harness]
            preset = "baseline"
            coverage_min = 91

            [tool.pytest.ini_options]
            addopts = "-q"
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["harness", "presets", "set", "strict"])

    cmd_presets()

    text = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert 'preset = "strict"' in text
    assert 'preset = "baseline"' not in text
    assert "coverage_min = 91" in text
    assert "[tool.pytest.ini_options]" in text


def test_cmd_presets_set_rejects_unknown_preset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "pkg"\nversion = "0.0.0"\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["harness", "presets", "set", "agent-safe"])

    with pytest.raises(SystemExit) as exc:
        cmd_presets()

    assert exc.value.code == 1
    assert "unsupported preset: agent-safe" in capsys.readouterr().out


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
