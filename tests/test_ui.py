from __future__ import annotations

from pathlib import Path

import pytest

from interlocks import ui
from interlocks.config import InterlockConfig


def _cfg(tmp_path: Path) -> InterlockConfig:
    return InterlockConfig(
        project_root=tmp_path,
        src_dir=tmp_path / "interlocks",
        test_dir=tmp_path / "tests",
        test_runner="pytest",
        test_invoker="python",
    )


def test_use_color_honors_no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    assert not ui.use_color()


def test_use_color_for_github_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    assert ui.use_color()


def test_verbose_chrome_is_suppressed_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(ui, "is_verbose", lambda: False)

    ui.banner(_cfg(tmp_path))
    ui.command_banner("check", _cfg(tmp_path))
    ui.section("Check")
    ui.stage_footer(1.2)
    ui.row("lint", "ruff check", "ok", state="ok")
    ui.kv_block([])

    assert capsys.readouterr().out == ""


def test_failure_row_prints_in_minimal_mode(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(ui, "is_verbose", lambda: False)

    ui.row("lint", "ruff check interlocks tests with a long command", "failed", state="fail")

    out = capsys.readouterr().out
    assert "[lint]" in out
    assert "failed" in out


def test_plain_len_strips_ansi_escape_sequences() -> None:
    assert ui._plain_len("\x1b[31mx\x1b[0m") == 1
