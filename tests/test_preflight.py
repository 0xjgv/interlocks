"""Preflight guard: refuse to run gated commands without a ``pyproject.toml``."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import interlocks
from interlocks.config import InterlockConfig, InterlockConfigError, clear_cache, require_pyproject
from interlocks.runner import preflight

# Package root of the interlocks under test — forced onto ``PYTHONPATH`` for subprocess
# probes so they always exercise the current source, not a stale editable install.
_INTERLOCK_PKG_ROOT = str(Path(interlocks.__file__).resolve().parent.parent)


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{_INTERLOCK_PKG_ROOT}{os.pathsep}{existing}" if existing else _INTERLOCK_PKG_ROOT
    )
    return env


def _cfg(root: Path) -> InterlockConfig:
    return InterlockConfig(
        project_root=root,
        src_dir=root,
        test_dir=root,
        test_runner="pytest",
        test_invoker="python",
    )


# ─────────────── require_pyproject ──────────────────────────────────


def test_require_pyproject_passes_when_file_exists(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    require_pyproject(_cfg(tmp_path))  # must not raise


def test_require_pyproject_raises_when_missing(tmp_path: Path) -> None:
    with pytest.raises(InterlockConfigError, match=r"no pyproject\.toml"):
        require_pyproject(_cfg(tmp_path))


def test_require_pyproject_points_at_init(tmp_path: Path) -> None:
    with pytest.raises(InterlockConfigError) as exc:
        require_pyproject(_cfg(tmp_path))
    assert "interlocks init" in str(exc.value)


# ─────────────── preflight() exit behaviour ─────────────────────────


def test_preflight_exempt_commands_never_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Utility commands must work without a pyproject."""
    monkeypatch.chdir(tmp_path)
    clear_cache()
    for command in ("help", "doctor", "init", "presets", "version"):
        preflight(command)

    captured = capsys.readouterr()
    assert captured.err == ""


def test_preflight_exits_two_when_gated_command_has_no_pyproject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    clear_cache()
    with pytest.raises(SystemExit) as exc:
        preflight("check")
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "no pyproject.toml" in captured.err


@pytest.mark.parametrize("changed_arg", ["--changed", "--changed=origin/main"])
def test_preflight_allows_check_changed_without_pyproject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    changed_arg: str,
) -> None:
    """``check --changed`` is progressive adoption — must not block on missing pyproject."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "check", changed_arg])
    clear_cache()
    preflight("check")  # must not raise or exit

    captured = capsys.readouterr()
    assert captured.err == ""


# ─────────────── end-to-end via subprocess ──────────────────────────


def test_cli_check_exits_two_without_pyproject(tmp_path: Path) -> None:
    """Running ``interlocks check`` outside any project surfaces a clear error, exit 2."""
    result = subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "check"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env=_subprocess_env(),
    )
    assert result.returncode == 2, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "no pyproject.toml" in result.stderr


def test_cli_help_works_without_pyproject(tmp_path: Path) -> None:
    """Help is exempt — users need it to recover from a missing pyproject."""
    result = subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env=_subprocess_env(),
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "Usage: interlocks <command>" in result.stdout
