"""Unit tests for interlocks.crash.boundary.

Focus: classification semantics and invariant I6 — a bug inside the crash
reporter MUST NOT mask the original exception.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from interlocks.config import InterlockConfigError, InterlockUserError
from interlocks.crash import boundary as boundary_mod
from interlocks.crash.boundary import CrashBoundary


def _trigger_interlocks_frame() -> None:
    """Raise from inside the interlocks package so ``_is_interlocks_exception`` matches."""
    raise RuntimeError("synthetic interlocks bug")


def _captured_runtime_error() -> RuntimeError:
    try:
        raise RuntimeError("synthetic interlocks bug")
    except RuntimeError as exc:
        return exc
    raise AssertionError("unreachable")


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


def test_capture_and_transport_submits_report_when_user_accepts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload: dict[str, Any] = {"fingerprint": "abc123", "exception_type": "RuntimeError"}
    local_path = tmp_path / "abc123.json"
    build_args: list[tuple[str, str, Path | None]] = []
    submitted: list[tuple[dict[str, Any], str, Path | None]] = []
    seen: list[tuple[str, float]] = []

    def fake_build_payload(
        exc: BaseException,
        *,
        subcommand: str,
        project_root: Path | None,
    ) -> dict[str, Any]:
        build_args.append((str(exc), subcommand, project_root))
        return payload

    monkeypatch.setattr(boundary_mod, "_safe_load_config", lambda: (None, tmp_path))
    monkeypatch.setattr(boundary_mod, "build_payload", fake_build_payload)
    monkeypatch.setattr(boundary_mod, "write_crash", lambda saved: local_path)
    monkeypatch.setattr(boundary_mod.time, "time", lambda: 12.5)
    monkeypatch.setattr(boundary_mod, "should_suppress_transport", lambda _fp, *, now: False)
    monkeypatch.setattr(boundary_mod, "prompt_for_report", lambda *, local_path: "report")
    monkeypatch.setattr(
        boundary_mod.BrowserTransport,
        "submit",
        lambda saved, *, repo, local_path: submitted.append((saved, repo, local_path)) or "url",
    )
    monkeypatch.setattr(
        boundary_mod,
        "record_seen",
        lambda fingerprint, *, now: seen.append((fingerprint, now)),
    )

    boundary_mod._capture_and_transport(_captured_runtime_error(), "check")

    assert build_args == [("synthetic interlocks bug", "check", tmp_path)]
    assert submitted == [(payload, "0xjgv/interlocks", local_path)]
    assert seen == [("abc123", 12.5)]


def test_capture_and_transport_records_skip_without_submit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submitted: list[dict[str, Any]] = []
    seen: list[str] = []

    monkeypatch.setattr(boundary_mod, "_safe_load_config", lambda: (None, tmp_path))
    monkeypatch.setattr(
        boundary_mod,
        "build_payload",
        lambda _exc, *, subcommand, project_root: {"fingerprint": "skip-me"},
    )
    monkeypatch.setattr(boundary_mod, "write_crash", lambda _payload: tmp_path / "skip-me.json")
    monkeypatch.setattr(boundary_mod.time, "time", lambda: 99.0)
    monkeypatch.setattr(boundary_mod, "should_suppress_transport", lambda _fp, *, now: False)
    monkeypatch.setattr(boundary_mod, "prompt_for_report", lambda *, local_path: "skip")
    monkeypatch.setattr(
        boundary_mod.BrowserTransport,
        "submit",
        lambda saved, *, repo, local_path: submitted.append(saved) or "url",
    )

    def fake_record_seen(fingerprint: str, *, now: float) -> None:
        assert now >= 0
        seen.append(fingerprint)

    monkeypatch.setattr(boundary_mod, "record_seen", fake_record_seen)

    boundary_mod._capture_and_transport(_captured_runtime_error(), "check")

    assert submitted == []
    assert seen == ["skip-me"]


def test_capture_and_transport_suppressed_before_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompted: list[Path | None] = []
    submitted: list[dict[str, Any]] = []
    seen: list[str] = []

    monkeypatch.setattr(boundary_mod, "_safe_load_config", lambda: (None, tmp_path))
    monkeypatch.setattr(
        boundary_mod,
        "build_payload",
        lambda _exc, *, subcommand, project_root: {"fingerprint": "seen-before"},
    )
    monkeypatch.setattr(
        boundary_mod,
        "write_crash",
        lambda _payload: tmp_path / "seen-before.json",
    )
    monkeypatch.setattr(boundary_mod.time, "time", lambda: 1.0)
    monkeypatch.setattr(boundary_mod, "should_suppress_transport", lambda _fp, *, now: True)
    monkeypatch.setattr(
        boundary_mod,
        "prompt_for_report",
        lambda *, local_path: prompted.append(local_path) or "report",
    )
    monkeypatch.setattr(
        boundary_mod.BrowserTransport,
        "submit",
        lambda saved, *, repo, local_path: submitted.append(saved) or "url",
    )

    def fake_record_seen(fingerprint: str, *, now: float) -> None:
        assert now >= 0
        seen.append(fingerprint)

    monkeypatch.setattr(boundary_mod, "record_seen", fake_record_seen)

    boundary_mod._capture_and_transport(_captured_runtime_error(), "check")

    assert prompted == []
    assert submitted == []
    assert seen == []
