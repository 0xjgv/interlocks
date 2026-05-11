"""Tests for the reusable GitHub Action helper and metadata."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from interlocks import github_action

_ACTION = (Path(__file__).resolve().parent.parent / "action.yml").read_text(encoding="utf-8")


def test_command_from_args_defaults_to_interlock_ci() -> None:
    assert github_action._command_from_args(()) == ["interlocks", "ci"]


def test_command_from_args_accepts_command_override() -> None:
    assert github_action._command_from_args(("--command", "interlocks ci --verbose")) == [
        "interlocks",
        "ci",
        "--verbose",
    ]


def test_write_summary_records_command_and_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    github_action.write_summary(["interlocks", "ci"], 0)

    assert summary.read_text(encoding="utf-8") == (
        "## interlocks CI\n\n- Command: `interlocks ci`\n- Result: passed\n"
    )


def test_write_summary_records_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    github_action.write_summary(["interlocks", "ci"], 2)

    assert "- Result: failed (exit 2)" in summary.read_text(encoding="utf-8")


def test_write_summary_noops_when_env_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    github_action.write_summary(["interlocks", "ci"], 0)

    assert not list(tmp_path.iterdir())


def test_main_exits_with_command_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    calls: list[list[str]] = []

    def fake_run(command: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert check is False
        return subprocess.CompletedProcess(command, 7)

    monkeypatch.setattr(github_action.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc:
        github_action.main(["--command", "interlocks ci"])

    assert exc.value.code == 7
    assert calls == [["interlocks", "ci"]]
    assert "- Result: failed (exit 7)" in summary.read_text(encoding="utf-8")


def test_action_metadata_delegates_to_interlock_ci() -> None:
    assert "using: composite" in _ACTION
    # interlocks 0.2 ships through `uv tool install` rather than pip — the
    # action sets up uv, restores the uvx cache, warms it, then runs offline.
    assert "astral-sh/setup-uv@" in _ACTION
    assert "default: uv tool install interlocks" in _ACTION
    assert "default: interlocks ci" in _ACTION
    assert "actions/cache@v4" in _ACTION
    assert "interlocks warm" in _ACTION
    assert 'UV_OFFLINE: "1"' in _ACTION
    assert 'python -m interlocks.github_action --command "${{ inputs.command }}"' in _ACTION
    assert "ruff" not in _ACTION
    assert "coverage run" not in _ACTION
    assert "pip install interlocks" not in _ACTION


def test_action_cache_key_covers_pin_material() -> None:
    """Cache key must hash both tools.py (pin table) and tools.txt (compiled hashes)."""
    hash_match = re.search(r"hashFiles\([^)]+\)", _ACTION)
    assert hash_match is not None, "no hashFiles() expression in action.yml cache key"
    hash_expr = hash_match.group()
    assert "tools.py" in hash_expr, "tools.py not in hashFiles expression"
    assert "tools.txt" in hash_expr, "tools.txt not in hashFiles expression"


def test_action_restore_keys_provides_fallback() -> None:
    """restore-keys must allow a partial cache hit when the exact pin set changes."""
    assert "restore-keys:" in _ACTION


def test_action_steps_ordered_cache_install_warm_run() -> None:
    """Steps must appear in the order: cache-restore → install → warm → offline run."""
    markers = [
        "actions/cache@",  # restore uvx cache
        "${{ inputs.install-command }}",  # install interlocks
        "interlocks warm",  # populate cache online
        "python -m interlocks.github_action",  # run with UV_OFFLINE=1
    ]
    positions = [_ACTION.index(m) for m in markers]
    assert positions == sorted(positions), (
        "action.yml steps are not in the expected order: cache-restore → install → warm → run"
    )


def test_action_uv_offline_only_after_warm_step() -> None:
    """UV_OFFLINE=1 must come after the warm step — warm runs online to fetch wheels."""
    warm_pos = _ACTION.index("interlocks warm")
    offline_pos = _ACTION.index('UV_OFFLINE: "1"')
    assert offline_pos > warm_pos, "UV_OFFLINE=1 must appear after 'interlocks warm', not before"
