"""Tests for explicit dependency freshness task."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from interlocks.tasks import deps_freshness as freshness_mod


@dataclass
class _StubProc:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def test_deps_freshness_passes_when_no_outdated_packages(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(freshness_mod.ui, "is_verbose", lambda: False)
    monkeypatch.setattr(freshness_mod, "capture", lambda _cmd: _StubProc(0, "[]"))

    freshness_mod.cmd_deps_freshness()

    out = capsys.readouterr().out
    assert "running" in out
    assert "dependencies current" in out
    assert out.index("running") < out.rindex("ok")


def test_deps_freshness_json_passes_when_no_outdated_packages(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "deps-freshness", "--json"])
    monkeypatch.setattr(freshness_mod, "capture", lambda _cmd: _StubProc(0, "[]"))

    freshness_mod.cmd_deps_freshness()

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["command"] == "deps-freshness"
    assert payload["passed"] is True
    assert payload["status"] == "ok"
    assert payload["outdated_count"] == 0
    assert payload["outdated"] == []
    assert "interlocks: [freshness] pip list --outdated running" in captured.err


def test_deps_freshness_fails_when_packages_are_outdated(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        freshness_mod,
        "capture",
        lambda _cmd: _StubProc(0, '[{"name":"pkg","version":"1.0","latest_version":"2.0"}]'),
    )

    with pytest.raises(SystemExit) as exc:
        freshness_mod.cmd_deps_freshness()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "1 outdated package" in out
    assert "pkg: 1.0 -> 2.0" in out


def test_deps_freshness_json_fails_when_packages_are_outdated(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "deps-freshness", "--json"])
    monkeypatch.setattr(
        freshness_mod,
        "capture",
        lambda _cmd: _StubProc(0, '[{"name":"pkg","version":"1.0","latest_version":"2.0"}]'),
    )

    with pytest.raises(SystemExit) as exc:
        freshness_mod.cmd_deps_freshness()

    payload = json.loads(capsys.readouterr().out)
    assert exc.value.code == 1
    assert payload["command"] == "deps-freshness"
    assert payload["passed"] is False
    assert payload["status"] == "failed"
    assert payload["outdated_count"] == 1
    assert payload["outdated"][0]["name"] == "pkg"
    assert payload["next_actions"]


def test_deps_freshness_fails_on_lookup_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(freshness_mod, "capture", lambda _cmd: _StubProc(2, stderr="network down"))

    with pytest.raises(SystemExit) as exc:
        freshness_mod.cmd_deps_freshness()

    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "package-index lookup failed" in out
    assert "network down" in out


def test_deps_freshness_json_fails_on_lookup_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "deps-freshness", "--json"])
    monkeypatch.setattr(freshness_mod, "capture", lambda _cmd: _StubProc(2, stderr="network down"))

    with pytest.raises(SystemExit) as exc:
        freshness_mod.cmd_deps_freshness()

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exc.value.code == 2
    assert payload["command"] == "deps-freshness"
    assert payload["passed"] is False
    assert payload["reason"] == "package-index lookup failed"
    assert payload["returncode"] == 2
    assert "network down" not in captured.out


def test_deps_freshness_falls_back_to_uv_when_target_python_has_no_pip(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(freshness_mod.ui, "is_verbose", lambda: False)
    monkeypatch.setattr(freshness_mod, "detect_target_interpreter", lambda _root: None)
    monkeypatch.setattr(
        freshness_mod.shutil,
        "which",
        lambda name: "/usr/bin/uv" if name == "uv" else None,
    )
    calls: list[list[str]] = []

    def fake_capture(cmd: list[str]) -> _StubProc:
        calls.append(cmd)
        if len(calls) == 1:
            return _StubProc(1, stderr="No module named pip")
        return _StubProc(0, "[]")

    monkeypatch.setattr(freshness_mod, "capture", fake_capture)

    freshness_mod.cmd_deps_freshness()

    assert calls[-1] == ["uv", "pip", "list", "--outdated", "--format=json"]
    out = capsys.readouterr().out
    assert "retrying with `uv pip list`" in out
    assert "dependencies current" in out


def test_deps_freshness_json_falls_back_to_uv_when_target_python_has_no_pip(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "deps-freshness", "--json"])
    monkeypatch.setattr(freshness_mod, "detect_target_interpreter", lambda _root: None)
    monkeypatch.setattr(
        freshness_mod.shutil,
        "which",
        lambda name: "/usr/bin/uv" if name == "uv" else None,
    )
    calls: list[list[str]] = []

    def fake_capture(cmd: list[str]) -> _StubProc:
        calls.append(cmd)
        if len(calls) == 1:
            return _StubProc(1, stderr="No module named pip")
        return _StubProc(0, "[]")

    monkeypatch.setattr(freshness_mod, "capture", fake_capture)

    freshness_mod.cmd_deps_freshness()

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert calls[-1] == ["uv", "pip", "list", "--outdated", "--format=json"]
    assert payload["passed"] is True
    assert payload["lookup_command"] == "uv pip list --outdated"
    assert payload["fallback_used"] is True
    assert "retrying with `uv pip list`" in captured.err


def test_freshness_retry_notice_json_is_exact(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "deps-freshness", "--json"])

    freshness_mod._freshness_retry_notice()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "interlocks: [freshness] "
        "deps-freshness: target Python has no pip module; retrying with `uv pip list`\n"
    )


def test_freshness_retry_notice_human_is_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notices: list[str] = []

    def fake_warn_skip(message: str) -> None:
        notices.append(message)

    monkeypatch.setattr(sys, "argv", ["interlocks", "deps-freshness"])
    monkeypatch.setattr(freshness_mod, "warn_skip", fake_warn_skip)

    freshness_mod._freshness_retry_notice()

    assert notices == [
        "deps-freshness: target Python has no pip module; retrying with `uv pip list`"
    ]


def test_freshness_row_defaults_to_ok_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows: list[tuple[str, str, str, str | None, str]] = []
    flushes = 0

    def fake_gate_row(
        label: str,
        command: str,
        status: str,
        *,
        detail: str | None,
        state: str,
    ) -> None:
        rows.append((label, command, status, detail, state))

    def fake_flush() -> None:
        nonlocal flushes
        flushes += 1

    monkeypatch.setattr(freshness_mod.ui, "gate_row", fake_gate_row)
    monkeypatch.setattr(freshness_mod.sys.stdout, "flush", fake_flush)

    freshness_mod._freshness_row("package-index lookup", "ok", detail="current")

    assert rows == [("freshness", "package-index lookup", "ok", "current", "ok")]
    assert flushes == 1


def test_uv_pip_list_cmd_targets_project_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from interlocks.config import clear_cache, load_config
    from interlocks.detect import expected_target_interpreter

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'sample'\nversion = '0.0.0'\n",
        encoding="utf-8",
    )
    python = expected_target_interpreter(tmp_path)
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    python.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    clear_cache()

    cmd = freshness_mod._uv_pip_list_cmd(load_config())

    assert cmd == [
        "uv",
        "pip",
        "list",
        "--python",
        str(python),
        "--outdated",
        "--format=json",
    ]
