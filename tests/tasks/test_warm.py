"""Tests for the `interlocks warm` task."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from interlocks.defaults.tools import DEFAULTS
from interlocks.tasks import warm as warm_mod


@dataclass
class _StubProc:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def _project_with_pyproject(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "warm-probe"\nversion = "0.0.0"\nrequires-python = ">=3.11"\n',
        encoding="utf-8",
    )
    return tmp_path


def test_warm_exits_when_uv_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(_project_with_pyproject(tmp_path))
    monkeypatch.setattr(warm_mod.shutil, "which", lambda _name: None)

    with pytest.raises(SystemExit) as exc:
        warm_mod.cmd_warm()

    assert exc.value.code == 1
    assert "uv` not found" in capsys.readouterr().out


def test_warm_json_exits_when_uv_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(_project_with_pyproject(tmp_path))
    monkeypatch.setattr(sys, "argv", ["interlocks", "warm", "--json"])
    monkeypatch.setattr(warm_mod.shutil, "which", lambda _name: None)

    with pytest.raises(SystemExit) as exc:
        warm_mod.cmd_warm()

    assert exc.value.code == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["command"] == "warm"
    assert payload["passed"] is False
    assert payload["status"] == "failed"
    assert payload["mode"] == "preflight"
    assert payload["failed_tools"] == [f"{name}=={version}" for name, version in DEFAULTS.items()]
    assert "Install uv" in payload["next_actions"][0]
    assert captured.err == ""


def test_warm_missing_uv_payload_is_stable() -> None:
    specs = [f"{name}=={version}" for name, version in DEFAULTS.items()]

    assert warm_mod._warm_missing_uv_payload() == {
        "command": "warm",
        "passed": False,
        "status": "failed",
        "mode": "preflight",
        "tool_count": len(DEFAULTS),
        "tools": specs,
        "cached_tools": [],
        "failed_tools": specs,
        "error": "`uv` not found on PATH",
        "next_actions": ["Install uv, then rerun `interlocks warm --json`."],
    }


def test_warm_uses_tools_txt_when_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(_project_with_pyproject(tmp_path))
    monkeypatch.setattr(warm_mod.shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(warm_mod.ui, "is_verbose", lambda: False)

    fake_tools_txt = tmp_path / "tools.txt"
    fake_tools_txt.write_text("ruff==0.15.12 --hash=sha256:abc\n", encoding="utf-8")
    monkeypatch.setattr(warm_mod, "_tools_txt_path", lambda: fake_tools_txt)

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], **_: object) -> _StubProc:
        captured["cmd"] = cmd
        return _StubProc(returncode=0)

    monkeypatch.setattr(warm_mod.subprocess, "run", fake_run)

    warm_mod.cmd_warm()

    assert captured["cmd"][:5] == ["uv", "pip", "install", "--require-hashes", "--target"]
    assert "-r" in captured["cmd"]
    out = capsys.readouterr().out
    assert "running" in out
    assert "ok" in out
    assert out.index("running") < out.rindex("ok")
    assert "hash-verified" in out
    assert "tools.txt missing" not in out


def test_warm_json_reports_tools_txt_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(_project_with_pyproject(tmp_path))
    monkeypatch.setattr(sys, "argv", ["interlocks", "warm", "--json"])
    monkeypatch.setattr(warm_mod.shutil, "which", lambda _name: "/usr/bin/uv")

    fake_tools_txt = tmp_path / "tools.txt"
    fake_tools_txt.write_text("ruff==0.15.12 --hash=sha256:abc\n", encoding="utf-8")
    monkeypatch.setattr(warm_mod, "_tools_txt_path", lambda: fake_tools_txt)
    monkeypatch.setattr(warm_mod.subprocess, "run", lambda *_a, **_kw: _StubProc(returncode=0))

    warm_mod.cmd_warm()

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["command"] == "warm"
    assert payload["passed"] is True
    assert payload["status"] == "ok"
    assert payload["mode"] == "tools.txt"
    assert payload["tools_txt"] == str(fake_tools_txt)
    assert payload["cached_tools"] == [f"{name}=={version}" for name, version in DEFAULTS.items()]
    assert payload["failed_tools"] == []
    assert "tools.txt running" in captured.err


def test_warm_tools_txt_failure_exits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(_project_with_pyproject(tmp_path))
    monkeypatch.setattr(warm_mod.shutil, "which", lambda _name: "/usr/bin/uv")
    fake_tools_txt = tmp_path / "tools.txt"
    fake_tools_txt.write_text("ruff==0.15.12\n", encoding="utf-8")
    monkeypatch.setattr(warm_mod, "_tools_txt_path", lambda: fake_tools_txt)
    monkeypatch.setattr(
        warm_mod.subprocess,
        "run",
        lambda *_a, **_kw: _StubProc(returncode=1, stderr="hash mismatch"),
    )

    with pytest.raises(SystemExit) as exc:
        warm_mod.cmd_warm()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "hash-pinned pre-fetch failed" in out
    assert "hash mismatch" in out


def test_warm_json_reports_tools_txt_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(_project_with_pyproject(tmp_path))
    monkeypatch.setattr(sys, "argv", ["interlocks", "warm", "--json"])
    monkeypatch.setattr(warm_mod.shutil, "which", lambda _name: "/usr/bin/uv")
    fake_tools_txt = tmp_path / "tools.txt"
    fake_tools_txt.write_text("ruff==0.15.12\n", encoding="utf-8")
    monkeypatch.setattr(warm_mod, "_tools_txt_path", lambda: fake_tools_txt)
    monkeypatch.setattr(
        warm_mod.subprocess,
        "run",
        lambda *_a, **_kw: _StubProc(returncode=1, stderr="hash mismatch"),
    )

    with pytest.raises(SystemExit) as exc:
        warm_mod.cmd_warm()

    assert exc.value.code == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["passed"] is False
    assert payload["mode"] == "tools.txt"
    assert payload["error"] == "hash-pinned pre-fetch failed"
    assert payload["output_excerpt"] == "hash mismatch"
    assert "hash mismatch" not in captured.err


def test_warm_falls_back_when_tools_txt_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(_project_with_pyproject(tmp_path))
    monkeypatch.setattr(warm_mod.shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(warm_mod.ui, "is_verbose", lambda: False)
    monkeypatch.setattr(warm_mod, "_tools_txt_path", lambda: tmp_path / "missing.txt")

    captured: list[list[str]] = []

    def fake_run(cmd: list[str], **_: object) -> _StubProc:
        captured.append(cmd)
        return _StubProc(returncode=0)

    monkeypatch.setattr(warm_mod.subprocess, "run", fake_run)

    warm_mod.cmd_warm()

    assert len(captured) == len(DEFAULTS)
    assert all(cmd[0] == "uvx" for cmd in captured)
    out = capsys.readouterr().out
    assert "tools.txt missing" in out
    assert "running" in out
    assert out.index("running") < out.rindex("ok")
    for name, version in DEFAULTS.items():
        assert f"warm: cached {name}=={version}" in out


def test_warm_fallback_uses_import_probe_for_mutmut(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(_project_with_pyproject(tmp_path))
    monkeypatch.setattr(warm_mod.shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(warm_mod.ui, "is_verbose", lambda: False)
    monkeypatch.setattr(warm_mod, "_tools_txt_path", lambda: tmp_path / "missing.txt")

    captured: list[list[str]] = []

    def fake_run(cmd: list[str], **_: object) -> _StubProc:
        captured.append(cmd)
        return _StubProc(returncode=0)

    monkeypatch.setattr(warm_mod.subprocess, "run", fake_run)

    warm_mod.cmd_warm()

    mutmut_cmd = next(cmd for cmd in captured if "interlocks-mutmut==3.5.1" in cmd)
    assert mutmut_cmd[-3:] == ["python", "-c", "import mutmut"]


def test_warm_json_reports_fallback_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(_project_with_pyproject(tmp_path))
    monkeypatch.setattr(sys, "argv", ["interlocks", "warm", "--json"])
    monkeypatch.setattr(warm_mod.shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(warm_mod, "_tools_txt_path", lambda: tmp_path / "missing.txt")
    monkeypatch.setattr(warm_mod.subprocess, "run", lambda *_a, **_kw: _StubProc(returncode=0))

    warm_mod.cmd_warm()

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["passed"] is True
    assert payload["mode"] == "uvx-probes"
    assert payload["tool_count"] == len(DEFAULTS)
    assert payload["cached_tools"] == [f"{name}=={version}" for name, version in DEFAULTS.items()]
    assert payload["failed_tools"] == []
    assert payload["warnings"] == [
        "tools.txt missing — falling back to per-tool uvx probes (no hash check)"
    ]
    assert "running" in captured.err


def test_warm_fallback_per_tool_failure_exits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(_project_with_pyproject(tmp_path))
    monkeypatch.setattr(warm_mod.shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(warm_mod, "_tools_txt_path", lambda: tmp_path / "missing.txt")

    def fake_run(cmd: list[str], **_: object) -> _StubProc:
        # Fail only the first tool to keep output deterministic.
        first_pkg = next(iter(DEFAULTS))
        if f"{first_pkg}==" in " ".join(cmd):
            return _StubProc(returncode=1, stderr="boom")
        return _StubProc(returncode=0)

    monkeypatch.setattr(warm_mod.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc:
        warm_mod.cmd_warm()

    assert exc.value.code == 1
    first_pkg = next(iter(DEFAULTS))
    assert f"failed to fetch {first_pkg}" in capsys.readouterr().out


def test_warm_json_reports_fallback_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(_project_with_pyproject(tmp_path))
    monkeypatch.setattr(sys, "argv", ["interlocks", "warm", "--json"])
    monkeypatch.setattr(warm_mod.shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(warm_mod, "_tools_txt_path", lambda: tmp_path / "missing.txt")

    def fake_run(cmd: list[str], **_: object) -> _StubProc:
        first_pkg = next(iter(DEFAULTS))
        if f"{first_pkg}==" in " ".join(cmd):
            return _StubProc(returncode=1, stderr="boom")
        return _StubProc(returncode=0)

    monkeypatch.setattr(warm_mod.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc:
        warm_mod.cmd_warm()

    assert exc.value.code == 1
    first_pkg, first_version = next(iter(DEFAULTS.items()))
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is False
    assert payload["mode"] == "uvx-probes"
    assert payload["failed_tools"] == [f"{first_pkg}=={first_version}"]
    assert payload["error"] == "one or more tools failed to fetch"


def test_warm_treats_empty_tools_txt_as_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A zero-byte tools.txt must take the per-tool fallback (not require-hashes)."""
    monkeypatch.chdir(_project_with_pyproject(tmp_path))
    monkeypatch.setattr(warm_mod.shutil, "which", lambda _name: "/usr/bin/uv")
    empty = tmp_path / "tools.txt"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setattr(warm_mod, "_tools_txt_path", lambda: empty)
    monkeypatch.setattr(warm_mod.subprocess, "run", lambda *_a, **_kw: _StubProc(returncode=0))

    warm_mod.cmd_warm()

    assert "tools.txt missing" in capsys.readouterr().out
