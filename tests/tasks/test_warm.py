"""Tests for the `interlocks warm` task."""

from __future__ import annotations

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


def test_warm_uses_tools_txt_when_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(_project_with_pyproject(tmp_path))
    monkeypatch.setattr(warm_mod.shutil, "which", lambda _name: "/usr/bin/uv")

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
    assert "hash-verified" in out
    assert "tools.txt missing" not in out


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


def test_warm_falls_back_when_tools_txt_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(_project_with_pyproject(tmp_path))
    monkeypatch.setattr(warm_mod.shutil, "which", lambda _name: "/usr/bin/uv")
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
    for name, version in DEFAULTS.items():
        assert f"warm: cached {name}=={version}" in out


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
