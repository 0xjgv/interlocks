"""Unit tests for interlocks.crash.boundary.

Focus: classification semantics and invariant I6 — a bug inside the crash
reporter MUST NOT mask the original exception.

Also probes preflight / user-config error cases:
- Missing pyproject.toml exits 2 without crash capture (via existing BDD scenario).
- Malformed pyproject.toml raises InterlockConfigError, handled as user error.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from interlocks.config import (
    InterlockConfigError,
    InterlockUserError,
    clear_cache,
    load_config,
)
from interlocks.crash import boundary as boundary_mod
from interlocks.crash.boundary import CrashBoundary


def _trigger_interlocks_frame() -> None:
    """Raise from inside the interlocks package so ``_is_interlocks_exception`` matches."""
    raise RuntimeError("synthetic interlocks bug")


def test_systemexit_passes_through_unchanged() -> None:
    boundary = CrashBoundary(subcommand="check")
    with pytest.raises(SystemExit) as excinfo, boundary:
        raise SystemExit(7)
    assert excinfo.value.code == 7


def test_keyboardinterrupt_passes_through_unchanged() -> None:
    boundary = CrashBoundary(subcommand="check")
    with pytest.raises(KeyboardInterrupt), boundary:
        raise KeyboardInterrupt()


def test_user_error_prints_clean_line_and_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    boundary = CrashBoundary(subcommand="check")
    with pytest.raises(SystemExit) as excinfo, boundary:
        raise InterlockConfigError("bad threshold")
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert captured.err.strip() == "interlocks: bad threshold"


def test_user_error_subclass_also_caught(capsys: pytest.CaptureFixture[str]) -> None:
    class _Custom(InterlockUserError):
        pass

    boundary = CrashBoundary(subcommand="check")
    with pytest.raises(SystemExit) as excinfo, boundary:
        raise _Custom("subclass message")
    assert excinfo.value.code == 2
    assert "subclass message" in capsys.readouterr().err


def test_non_interlocks_exception_passes_through_uncaptured(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bug raised from outside the interlocks package must not enter capture."""
    captured: list[str] = []
    monkeypatch.setattr(
        boundary_mod,
        "_capture_and_transport",
        lambda exc, sub: captured.append(sub),
    )
    boundary = CrashBoundary(subcommand="check")
    with pytest.raises(ValueError), boundary:
        raise ValueError("from user code")
    assert captured == []
    assert capsys.readouterr().err == ""


def test_invariant_i6_capture_failure_does_not_mask_original(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invariant I6: a bug inside the crash reporter MUST NOT mask the original exception.

    We force ``_capture_and_transport`` to raise, then assert that:
      1. The original ``RuntimeError`` still propagates out of the ``with`` block.
      2. A single ``(crash reporter failed: ...)`` line is written to stderr.
    """

    def _broken_capture(_exc: BaseException, _sub: str) -> None:
        raise RuntimeError("capture pipeline boom")

    monkeypatch.setattr(boundary_mod, "_capture_and_transport", _broken_capture)
    # The synthetic raiser lives in tests/, not interlocks/, so force the
    # classifier to treat it as an interlocks-origin bug for this test.
    monkeypatch.setattr(boundary_mod, "_is_interlocks_exception", lambda _exc: True)

    boundary = CrashBoundary(subcommand="check")
    with pytest.raises(RuntimeError) as excinfo, boundary:
        _trigger_interlocks_frame()

    assert str(excinfo.value) == "synthetic interlocks bug"
    err = capsys.readouterr().err
    assert "(crash reporter failed: capture pipeline boom)" in err
    # Exactly one reporter-failure line — the wrapper swallows once and re-raises.
    assert err.count("crash reporter failed") == 1


def test_inject_env_raises_only_when_subcommand_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTERLOCKS_CRASH_INJECT", "lint")
    boundary = CrashBoundary(subcommand="lint")
    with pytest.raises(RuntimeError, match="injected for crash boundary test"):
        boundary.maybe_inject_for_test()


def test_inject_env_inert_when_subcommand_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTERLOCKS_CRASH_INJECT", "lint")
    boundary = CrashBoundary(subcommand="check")
    boundary.maybe_inject_for_test()  # must not raise


def test_inject_env_inert_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTERLOCKS_CRASH_INJECT", raising=False)
    boundary = CrashBoundary(subcommand="lint")
    boundary.maybe_inject_for_test()  # must not raise


def test_safe_load_config_returns_none_when_load_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken pyproject must not block local capture — config falls back to None."""

    def _explode() -> None:
        raise RuntimeError("pyproject is corrupt")

    monkeypatch.setattr(boundary_mod, "load_config", _explode)
    cfg, project_root = boundary_mod._safe_load_config()
    assert cfg is None
    assert project_root is None


def test_safe_load_config_returns_cfg_and_project_root_on_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from interlocks.config import InterlockConfig

    cfg = InterlockConfig(
        project_root=tmp_path,
        src_dir=tmp_path / "src",
        test_dir=tmp_path / "tests",
        test_runner="pytest",
        test_invoker="python",
    )
    monkeypatch.setattr(boundary_mod, "load_config", lambda: cfg)
    loaded, root = boundary_mod._safe_load_config()
    assert loaded is cfg
    assert root == tmp_path


# ---------------------------------------------------------------------------
# Preflight / user-config error classification probes
# ---------------------------------------------------------------------------


def test_malformed_toml_is_user_error_not_crash(tmp_path: Path) -> None:
    """_load_pyproject converts TOMLDecodeError to InterlockConfigError.

    If raw TOMLDecodeError escaped, the boundary would misclassify it as an
    internal crash (call stack has interlocks frames) and trigger crash capture.
    InterlockConfigError is an InterlockUserError, so the boundary exits 2 cleanly.
    pytest.raises(InterlockConfigError) proves no raw TOMLDecodeError escaped.
    """
    from interlocks.config import _load_pyproject

    (tmp_path / "pyproject.toml").write_text("[invalid\nnot toml\n", encoding="utf-8")
    with pytest.raises(InterlockConfigError, match=r"pyproject\.toml is not valid TOML"):
        _load_pyproject(tmp_path)


def test_config_error_from_malformed_toml_exits_2_via_boundary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """InterlockConfigError raised inside the boundary exits 2, no crash capture.

    Simulates a PREFLIGHT_EXEMPT task calling load_config() for a malformed TOML
    while inside the CrashBoundary — boundary handles it as a user error, not a crash.
    """
    captured: list[str] = []
    monkeypatch.setattr(
        boundary_mod,
        "_capture_and_transport",
        lambda exc, sub: captured.append(sub),
    )

    (tmp_path / "pyproject.toml").write_text("[bad\n", encoding="utf-8")
    clear_cache()

    boundary = CrashBoundary(subcommand="lint")
    with pytest.raises(SystemExit) as excinfo, boundary:
        load_config(tmp_path)

    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "interlocks:" in err
    assert "not valid TOML" in err
    assert captured == []
