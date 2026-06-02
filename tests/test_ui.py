from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from interlocks import ui
from interlocks.config import InterlockConfig

_REAL_IS_VERBOSE = ui.is_verbose


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

    ui.row("lint", "ruff check interlocks gate tests with a long command", "failed", state="fail")

    out = capsys.readouterr().out
    assert "[lint]" in out
    assert "failed" in out


def test_gate_row_prints_ok_in_minimal_mode(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A plain `ok` row is verbose-gated; `gate_row` is not — stage gates always show.
    monkeypatch.setattr(ui, "is_verbose", lambda: False)

    ui.row("lint", "ruff check", "ok", state="ok")
    assert capsys.readouterr().out == ""

    ui.gate_row("lint", "ruff check", "ok", state="ok")
    out = capsys.readouterr().out
    assert "[lint]" in out
    assert "ok" in out


def test_gate_row_silent_under_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # --json dominates: gate_row stays silent so stdout is exactly one JSON object.
    monkeypatch.setattr(sys, "argv", ["interlocks", "check", "--json"])

    ui.gate_row("lint", "ruff check", "ok", state="ok")

    assert capsys.readouterr().out == ""


def test_group_header_prints_in_minimal_mode(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A `section` header is verbose-gated; `group_header` is not — first-touch
    # navigation labels must render at default verbosity.
    monkeypatch.setattr(ui, "is_verbose", lambda: False)

    ui.section("Start here")
    assert capsys.readouterr().out == ""

    ui.group_header("Start here")
    out = capsys.readouterr().out
    assert out == "\nStart here:\n"


def test_group_header_silent_under_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # --json dominates: group_header stays silent so stdout is exactly one JSON object.
    monkeypatch.setattr(sys, "argv", ["interlocks", "help", "--json"])

    ui.group_header("Start here")

    assert capsys.readouterr().out == ""


def test_print_next_actions_formats_human_lines(capsys: pytest.CaptureFixture[str]) -> None:
    ui.print_next_actions(["Run `interlocks check`.", "Sync dependencies."], indent="  ")

    assert capsys.readouterr().out == (
        "  next: run `interlocks check`.\n  next: sync dependencies.\n"
    )


def test_plain_len_strips_ansi_escape_sequences() -> None:
    assert ui._plain_len("\x1b[31mx\x1b[0m") == 1


def test_is_json_true_when_flag_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "ci", "--json"])
    assert ui.is_json() is True


def test_is_json_false_when_flag_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "ci"])
    assert ui.is_json() is False


def test_is_verbose_true_when_flag_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ui, "is_verbose", _REAL_IS_VERBOSE)
    monkeypatch.setattr(sys, "argv", ["interlocks", "ci", "--verbose"])
    assert ui.is_verbose() is True


def test_is_verbose_false_when_flag_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ui, "is_verbose", _REAL_IS_VERBOSE)
    monkeypatch.setattr(sys, "argv", ["interlocks", "ci"])
    assert ui.is_verbose() is False


def test_print_json_single_line_compact_with_newline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    ui.print_json({"command": "ci", "passed": True, "gates": []})
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    assert out.endswith("\n")
    assert ", " not in out and ": " not in out  # compact separators
    assert json.loads(out) == {"command": "ci", "passed": True, "gates": []}


def test_print_json_preserves_insertion_order(
    capsys: pytest.CaptureFixture[str],
) -> None:
    ui.print_json({"command": "x", "zeta": 1, "alpha": 2})
    out = capsys.readouterr().out.strip()
    assert out.index('"command"') < out.index('"zeta"') < out.index('"alpha"')


@pytest.mark.parametrize("extra", [[], ["--verbose"]])
def test_chrome_primitives_silent_under_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    extra: list[str],
) -> None:
    # --json dominates --verbose: chrome stays silent even with --verbose present.
    monkeypatch.setattr(sys, "argv", ["interlocks", "ci", "--json", *extra])
    ui.banner(_cfg(tmp_path))
    ui.command_banner("ci", None)
    ui.section("CI Checks")
    ui.row("lint", "ruff check", "failed", state="fail")
    ui.print_next_actions(["Run `interlocks check`."])
    ui.stage_footer(1.0)
    assert capsys.readouterr().out == ""
