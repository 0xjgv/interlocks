from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from interlocks.acceptance_trace import (
    _tracer,
    collect_trace_evidence,
    format_trace_evidence,
    load_trace_evidence,
    trace_can_wrap_command,
    trace_evidence_path,
    trace_wrapper_cmd,
)


def _frame(name: str, globals_: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(f_code=SimpleNamespace(co_name=name), f_globals=globals_)


def test_trace_can_wrap_command_requires_env_and_module_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("INTERLOCKS_ACCEPTANCE_TRACE_IN_PROCESS", raising=False)
    assert not trace_can_wrap_command([sys.executable, "-m", "pytest"])

    monkeypatch.setenv("INTERLOCKS_ACCEPTANCE_TRACE_IN_PROCESS", "1")
    assert trace_can_wrap_command([sys.executable, "-m", "pytest"])
    assert not trace_can_wrap_command([sys.executable, "-c", "print(1)"])
    assert not trace_can_wrap_command([sys.executable, "-m"])


def test_trace_wrapper_cmd_embeds_payload(tmp_path: Path) -> None:
    cmd = trace_wrapper_cmd(
        tmp_path,
        ("pkg.mod:fn",),
        [sys.executable, "-m", "pytest", "tests/features"],
    )

    assert cmd[:3] == [sys.executable, "-m", "interlocks.acceptance_trace"]
    payload = json.loads(cmd[3])
    assert payload == {
        "project_root": str(tmp_path),
        "public_symbols": ["pkg.mod:fn"],
        "runner_cmd": [sys.executable, "-m", "pytest", "tests/features"],
    }


def test_trace_failure_is_diagnostic_and_preserves_runner_exit_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INTERLOCKS_ACCEPTANCE_TRACE_FAIL", "1")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "interlocks.acceptance_trace",
            json.dumps({
                "project_root": str(tmp_path),
                "public_symbols": ["interlocks.cli:main"],
                "runner_cmd": [sys.executable, "-m", "interlocks.cli", "help", "--quiet"],
            }),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    evidence = load_trace_evidence(tmp_path)
    assert result.returncode == 0
    assert evidence is not None
    assert evidence.failure == "forced trace instrumentation failure"
    assert "trace instrumentation failed" in format_trace_evidence(evidence)


def test_collect_trace_evidence_records_reached_symbol(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = tmp_path / "sample_runner.py"
    runner.write_text(
        "def tracked():\n    return None\n\ntracked()\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    result = collect_trace_evidence(
        tmp_path,
        ("sample_runner:tracked",),
        [sys.executable, "-m", "sample_runner"],
    )

    evidence = load_trace_evidence(tmp_path)
    assert result == 0
    assert evidence is not None
    assert evidence.reached_symbols == ("sample_runner:tracked",)


def test_collect_trace_evidence_returns_one_for_unrunnable_command(tmp_path: Path) -> None:
    result = collect_trace_evidence(
        tmp_path,
        ("interlocks.cli:main",),
        [sys.executable, "-c", "pass"],
    )

    evidence = load_trace_evidence(tmp_path)
    assert result == 1
    assert evidence is not None
    assert evidence.unreached_symbols == ("interlocks.cli:main",)


def test_missing_trace_evidence_is_advisory_setup_hint(tmp_path: Path) -> None:
    assert load_trace_evidence(tmp_path) is None
    assert "advisory runtime detail" in format_trace_evidence(None)


def test_tracer_records_call_event_with_matching_module() -> None:
    reached: set[str] = set()
    trace = _tracer(("pkg.mod:foo",), reached)

    result = trace(_frame("foo", {"__name__": "pkg.mod"}), "call", None)

    assert result is trace
    assert reached == {"pkg.mod:foo"}


def test_tracer_ignores_non_call_events() -> None:
    reached: set[str] = set()
    trace = _tracer(("pkg.mod:foo",), reached)

    trace(_frame("foo", {"__name__": "pkg.mod"}), "line", None)

    assert reached == set()


def test_tracer_ignores_unknown_function_names() -> None:
    reached: set[str] = set()
    trace = _tracer(("pkg.mod:foo",), reached)

    trace(_frame("bar", {"__name__": "pkg.mod"}), "call", None)

    assert reached == set()


def test_tracer_ignores_unknown_modules() -> None:
    reached: set[str] = set()
    trace = _tracer(("pkg.mod:foo",), reached)

    trace(_frame("foo", {"__name__": "other.mod"}), "call", None)

    assert reached == set()


def test_tracer_matches_via_spec_name_when_globals_module_misses() -> None:
    reached: set[str] = set()
    trace = _tracer(("pkg.mod:foo",), reached)

    class _Spec:
        name = "pkg.mod"

    trace(_frame("foo", {"__name__": "wrong", "__spec__": _Spec()}), "call", None)

    assert reached == {"pkg.mod:foo"}


def test_trace_evidence_reports_reached_and_unreached_symbols(tmp_path: Path) -> None:
    trace_evidence_path(tmp_path).parent.mkdir()
    trace_evidence_path(tmp_path).write_text(
        json.dumps({
            "symbols": [
                {"symbol": "interlocks.cli:main", "reached": True},
                {"symbol": "interlocks.tasks.acceptance:cmd_acceptance", "reached": False},
            ]
        }),
        encoding="utf-8",
    )

    evidence = load_trace_evidence(tmp_path)

    assert evidence is not None
    report = format_trace_evidence(evidence)
    assert "reached public symbols: interlocks.cli:main" in report
    assert "unreached public symbols: interlocks.tasks.acceptance:cmd_acceptance" in report
