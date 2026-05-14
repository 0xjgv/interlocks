"""In-process unit tests for ``interlocks.lintfix.verify``.

``apply_with_verify`` / ``apply_many_with_verify`` orchestrate snapshot →
apply → verify → restore. The ruff apply step and the verifier subprocess are
the two external seams; both are monkeypatched here so the snapshot/restore
invariant can be checked against real files without running ruff or a verifier.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from interlocks.lintfix import verify as verify_mod

_ORIG = "ORIGINAL\n"
_MUTATED = "MUTATED\n"


def _completed(rc: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["ruff"], rc, stdout, stderr)


@pytest.fixture
def target(tmp_path: Path) -> str:
    """A tracked source file with known contents; returns its absolute path."""
    f = tmp_path / "sample.py"
    f.write_text(_ORIG, encoding="utf-8")
    return str(f)


def _mutating_apply(rc: int):
    """Build a fake ``apply_rule`` that rewrites every target then returns ``rc``."""

    def _apply(_rule: str, files: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        for f in files:
            Path(f).write_text(_MUTATED, encoding="utf-8")
        return _completed(rc)

    return _apply


# ─────────────── apply_with_verify ────────────────────────────────


def test_apply_with_verify_ruff_failure_restores(
    target: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(verify_mod, "apply_rule", _mutating_apply(2))
    result = verify_mod.apply_with_verify(rule="I001", files=(target,), verify_cmd=["true"])
    assert result.applied is False
    assert result.returncode == 2
    assert result.restored is True
    # ruff crashed → verifier never ran → tree restored.
    assert Path(target).read_text(encoding="utf-8") == _ORIG


def test_apply_with_verify_pass_keeps_mutation(
    target: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(verify_mod, "apply_rule", _mutating_apply(0))
    monkeypatch.setattr(verify_mod, "capture", lambda _cmd: _completed(0))
    result = verify_mod.apply_with_verify(rule="I001", files=(target,), verify_cmd=["true"])
    assert result.applied is True
    assert result.restored is False
    assert Path(target).read_text(encoding="utf-8") == _MUTATED


def test_apply_with_verify_verify_failure_restores(
    target: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(verify_mod, "apply_rule", _mutating_apply(0))
    monkeypatch.setattr(verify_mod, "capture", lambda _cmd: _completed(1, stderr="nope"))
    result = verify_mod.apply_with_verify(rule="I001", files=(target,), verify_cmd=["false"])
    assert result.applied is False
    assert result.returncode == 1
    assert result.restored is True
    assert Path(target).read_text(encoding="utf-8") == _ORIG


# ─────────────── apply_many_with_verify ───────────────────────────


def test_apply_many_empty_batch_is_noop() -> None:
    result = verify_mod.apply_many_with_verify(rules_and_files=(), verify_cmd=["true"])
    assert result.applied is True
    assert result.returncode == 0
    assert result.applied_rules == ()
    assert result.restored is False


def test_apply_many_mid_batch_ruff_failure_restores(
    target: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def _apply(rule: str, files: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        calls.append(rule)
        for f in files:
            Path(f).write_text(_MUTATED, encoding="utf-8")
        # First rule succeeds, second crashes ruff.
        return _completed(0 if rule == "I001" else 2)

    monkeypatch.setattr(verify_mod, "apply_rule", _apply)
    result = verify_mod.apply_many_with_verify(
        rules_and_files=(("I001", (target,)), ("W292", (target,))),
        verify_cmd=["true"],
    )
    assert result.applied is False
    assert result.returncode == 2
    assert result.failed_rule == "W292"
    assert result.applied_rules == ("I001",)
    assert result.restored is True
    # Whole batch rolled back — not just the most recent rule.
    assert Path(target).read_text(encoding="utf-8") == _ORIG
    assert calls == ["I001", "W292"]


def test_apply_many_all_applied_verify_pass(target: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify_mod, "apply_rule", _mutating_apply(0))
    monkeypatch.setattr(verify_mod, "capture", lambda _cmd: _completed(0))
    result = verify_mod.apply_many_with_verify(
        rules_and_files=(("I001", (target,)), ("W292", (target,))),
        verify_cmd=["true"],
    )
    assert result.applied is True
    assert result.applied_rules == ("I001", "W292")
    assert result.restored is False
    assert Path(target).read_text(encoding="utf-8") == _MUTATED


def test_apply_many_verify_failure_restores(target: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify_mod, "apply_rule", _mutating_apply(0))
    monkeypatch.setattr(verify_mod, "capture", lambda _cmd: _completed(3, stderr="bad"))
    result = verify_mod.apply_many_with_verify(
        rules_and_files=(("I001", (target,)),),
        verify_cmd=["false"],
    )
    assert result.applied is False
    assert result.returncode == 3
    assert result.applied_rules == ("I001",)
    assert result.restored is True
    assert Path(target).read_text(encoding="utf-8") == _ORIG
