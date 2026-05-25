from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from interlocks import behavior_attribution_trace as trace_mod
from interlocks.behavior_attribution import load_evidence, write_evidence
from interlocks.behavior_attribution_trace import (
    _CURRENT_SCENARIO,
    EVENTS_ENV,
    PAYLOAD_ENV,
    SCENARIO_ENV,
    _current_scenario_payload,
    _decode_scenario_key,
    _encode_scenario_key,
    _install_subprocess_probe,
    _merge_subprocess_events,
    _parse_subprocess_event,
    _probe_env,
    _record_current_process_events,
    _scenario_line,
    _supports_python_sitecustomize,
    _tracer,
    _tracer_for_subprocess,
    _write_reached_events,
)


def _frame(name: str, globals_: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(f_code=SimpleNamespace(co_name=name), f_globals=globals_)


def _assert_probe_call(
    call: dict[str, object],
    events_path: Path,
    public_symbols: list[str],
) -> None:
    kwargs = call["kwargs"]
    assert isinstance(kwargs, dict)
    env = kwargs["env"]
    assert isinstance(env, dict)
    assert env[EVENTS_ENV] == str(events_path)
    assert json.loads(env[PAYLOAD_ENV]) == {"public_symbols": public_symbols}


def test_tracer_records_symbol_for_current_scenario(tmp_path: Path) -> None:
    reached: dict[tuple[Path, int], set[str]] = {}
    scenario_key = (tmp_path / "feature.feature", 4)
    token = _CURRENT_SCENARIO.set(scenario_key)
    try:
        trace = _tracer(("pkg.mod:foo",), reached)
        result = trace(_frame("foo", {"__name__": "pkg.mod"}), "call", None)
    finally:
        _CURRENT_SCENARIO.reset(token)

    assert result is trace
    assert reached == {scenario_key: {"pkg.mod:foo"}}


def test_tracer_ignores_calls_without_current_scenario(tmp_path: Path) -> None:
    reached: dict[tuple[Path, int], set[str]] = {}
    trace = _tracer(("pkg.mod:foo",), reached)

    trace(_frame("foo", {"__name__": "pkg.mod"}), "call", None)

    assert reached == {}


def test_tracer_ignores_non_call_events(tmp_path: Path) -> None:
    reached: dict[tuple[Path, int], set[str]] = {}
    token = _CURRENT_SCENARIO.set((tmp_path / "feature.feature", 4))
    try:
        trace = _tracer(("pkg.mod:foo",), reached)
        trace(_frame("foo", {"__name__": "pkg.mod"}), "line", None)
    finally:
        _CURRENT_SCENARIO.reset(token)

    assert reached == {}


def test_tracer_matches_via_spec_name(tmp_path: Path) -> None:
    reached: dict[tuple[Path, int], set[str]] = {}
    scenario_key = (tmp_path / "feature.feature", 4)

    class _Spec:
        name = "pkg.mod"

    token = _CURRENT_SCENARIO.set(scenario_key)
    try:
        trace = _tracer(("pkg.mod:foo",), reached)
        trace(_frame("foo", {"__name__": "wrong", "__spec__": _Spec()}), "call", None)
    finally:
        _CURRENT_SCENARIO.reset(token)

    assert reached == {scenario_key: {"pkg.mod:foo"}}


def test_write_evidence_round_trips(tmp_path: Path) -> None:
    path = tmp_path / ".interlocks" / "behavior-attribution.json"
    write_evidence(
        path,
        reached_by_scenario={(tmp_path / "x.feature", 3): {"pkg.mod:foo"}},
        created_at=123.0,
    )

    evidence = load_evidence(path)

    assert evidence is not None
    assert evidence.created_at == 123.0
    assert evidence.scenarios[0].reached_symbols == frozenset({"pkg.mod:foo"})


def test_write_evidence_emits_stable_json_contract(tmp_path: Path) -> None:
    path = tmp_path / "nested" / ".interlocks" / "behavior-attribution.json"
    expected = {
        "created_at": 123.0,
        "failure": "trace failed",
        "scenarios": [
            {
                "feature_path": str(tmp_path / "a.feature"),
                "scenario_line": 3,
                "reached_symbols": ["pkg.mod:foo"],
            },
            {
                "feature_path": str(tmp_path / "b.feature"),
                "scenario_line": 8,
                "reached_symbols": ["a", "z"],
            },
        ],
    }

    write_evidence(
        path,
        reached_by_scenario={
            (tmp_path / "b.feature", 8): {"z", "a"},
            (tmp_path / "a.feature", 3): {"pkg.mod:foo"},
        },
        created_at=123.0,
        failure="trace failed",
    )

    raw = path.read_text(encoding="utf-8")
    assert raw == json.dumps(expected, sort_keys=True) + "\n"
    assert json.loads(raw) == expected


def test_write_evidence_reuses_existing_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / ".interlocks" / "behavior-attribution.json"
    path.parent.mkdir()

    write_evidence(path, reached_by_scenario={}, created_at=1.0)
    write_evidence(path, reached_by_scenario={}, created_at=2.0)

    assert json.loads(path.read_text(encoding="utf-8"))["created_at"] == 2.0


def test_write_evidence_uses_explicit_utf8_encoding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / ".interlocks" / "behavior-attribution.json"
    calls: list[str | None] = []
    path_type = type(path)
    original = path_type.write_text

    def spy_write_text(
        self: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        calls.append(encoding)
        return original(self, data, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(path_type, "write_text", spy_write_text)

    write_evidence(path, reached_by_scenario={}, created_at=123.0)

    assert calls == ["utf-8"]


def test_subprocess_probe_records_symbols_to_events_file(tmp_path: Path) -> None:
    module = tmp_path / "sample.py"
    module.write_text("def tracked():\n    return None\n\ntracked()\n", encoding="utf-8")
    events = tmp_path / "events.jsonl"
    scenario_key = (tmp_path / "feature.feature", 4)
    (tmp_path / "sitecustomize.py").write_text(
        "import interlocks.behavior_attribution_trace\n", encoding="utf-8"
    )
    env = {
        "PYTHONPATH": ":".join((str(tmp_path), str(Path.cwd()))),
        SCENARIO_ENV: _encode_scenario_key(scenario_key),
        EVENTS_ENV: str(events),
        PAYLOAD_ENV: json.dumps({"public_symbols": ["sample:tracked"]}),
    }

    result = subprocess.run(
        [sys.executable, "-m", "sample"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    reached: dict[tuple[Path, int], set[str]] = {}
    _merge_subprocess_events(events, reached)
    assert result.returncode == 0
    assert reached == {scenario_key: {"sample:tracked"}}


def test_probe_env_uses_context_scenario_and_installs_sitecustomize(tmp_path: Path) -> None:
    scenario_key = (tmp_path / "feature.feature", 4)
    token = _CURRENT_SCENARIO.set(scenario_key)
    try:
        env = _probe_env(
            {"PYTHONPATH": "existing"},
            ("pkg.mod:foo",),
            tmp_path / "events.jsonl",
        )
    finally:
        _CURRENT_SCENARIO.reset(token)

    assert env is not None
    assert env[SCENARIO_ENV] == _encode_scenario_key(scenario_key)
    assert env[EVENTS_ENV] == str(tmp_path / "events.jsonl")
    assert json.loads(env[PAYLOAD_ENV]) == {"public_symbols": ["pkg.mod:foo"]}
    assert env["PYTHONPATH"].startswith(str(tmp_path))
    assert (tmp_path / "sitecustomize.py").read_text(encoding="utf-8")


def test_probe_env_uses_existing_scenario_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    scenario_key = (tmp_path / "feature.feature", 7)
    monkeypatch.setenv(SCENARIO_ENV, _encode_scenario_key(scenario_key))

    env = _probe_env(None, ("pkg.mod:foo",), tmp_path / "events.jsonl")

    assert env is not None
    assert env[SCENARIO_ENV] == _encode_scenario_key(scenario_key)


def test_probe_env_skips_without_scenario_or_mapping(tmp_path: Path) -> None:
    assert _probe_env(None, ("pkg.mod:foo",), tmp_path / "events.jsonl") is None
    token = _CURRENT_SCENARIO.set((tmp_path / "feature.feature", 4))
    try:
        assert _probe_env([], ("pkg.mod:foo",), tmp_path / "events.jsonl") is None
    finally:
        _CURRENT_SCENARIO.reset(token)


def test_install_subprocess_probe_wraps_python_commands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(*args: object, **kwargs: object) -> str:
        calls.append({"args": args, "kwargs": kwargs})
        return "done"

    monkeypatch.setattr("interlocks.behavior_attribution_trace.subprocess.run", fake_run)
    token = _CURRENT_SCENARIO.set((tmp_path / "feature.feature", 4))
    try:
        _install_subprocess_probe(("pkg.mod:foo",), tmp_path / "events.jsonl")
        result = subprocess.run([sys.executable, "-m", "sample"], check=False)
    finally:
        _CURRENT_SCENARIO.reset(token)

    assert result == "done"
    kwargs = calls[0]["kwargs"]
    assert isinstance(kwargs, dict)
    env = kwargs["env"]
    assert isinstance(env, dict)
    assert env[EVENTS_ENV] == str(tmp_path / "events.jsonl")


def test_install_subprocess_probe_skips_non_python_commands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(*args: object, **kwargs: object) -> str:
        calls.append({"args": args, "kwargs": kwargs})
        return "done"

    monkeypatch.setattr("interlocks.behavior_attribution_trace.subprocess.run", fake_run)
    token = _CURRENT_SCENARIO.set((tmp_path / "feature.feature", 4))
    try:
        _install_subprocess_probe(("pkg.mod:foo",), tmp_path / "events.jsonl")
        result = subprocess.run(["git", "status"], check=False)
    finally:
        _CURRENT_SCENARIO.reset(token)

    assert result == "done"
    kwargs = calls[0]["kwargs"]
    assert isinstance(kwargs, dict)
    assert "env" not in kwargs


def test_install_subprocess_probe_refreshes_existing_run_and_popen_wrappers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_calls: list[dict[str, object]] = []
    popen_calls: list[dict[str, object]] = []

    def fake_run(*args: object, **kwargs: object) -> str:
        run_calls.append({"args": args, "kwargs": kwargs})
        return "run-result"

    def fake_popen(*args: object, **kwargs: object) -> str:
        popen_calls.append({"args": args, "kwargs": kwargs})
        return "popen-result"

    first_events = tmp_path / "first.jsonl"
    second_events = tmp_path / "second.jsonl"

    monkeypatch.setattr(trace_mod, "_PATCHED_RUN", None)
    monkeypatch.setattr(trace_mod, "_PATCHED_POPEN", None)
    monkeypatch.setattr(trace_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(trace_mod.subprocess, "Popen", fake_popen)

    _install_subprocess_probe(("pkg.mod:first",), first_events)
    run_wrapper = trace_mod.subprocess.run
    popen_wrapper = trace_mod.subprocess.Popen

    assert callable(run_wrapper)
    assert callable(popen_wrapper)
    assert run_wrapper is trace_mod._PATCHED_RUN
    assert popen_wrapper is trace_mod._PATCHED_POPEN

    token = _CURRENT_SCENARIO.set((tmp_path / "feature.feature", 4))
    try:
        assert trace_mod.subprocess.run([sys.executable, "-m", "sample"]) == "run-result"
        assert trace_mod.subprocess.Popen([sys.executable, "-m", "sample"]) == "popen-result"
    finally:
        _CURRENT_SCENARIO.reset(token)

    _assert_probe_call(run_calls[0], first_events, ["pkg.mod:first"])
    _assert_probe_call(popen_calls[0], first_events, ["pkg.mod:first"])
    run_calls.clear()
    popen_calls.clear()

    _install_subprocess_probe(("pkg.mod:second", "pkg.mod:third"), second_events)

    assert trace_mod.subprocess.run is run_wrapper
    assert trace_mod.subprocess.Popen is popen_wrapper

    token = _CURRENT_SCENARIO.set((tmp_path / "feature.feature", 4))
    try:
        assert trace_mod.subprocess.run([sys.executable, "-m", "sample"]) == "run-result"
        assert trace_mod.subprocess.Popen([sys.executable, "-m", "sample"]) == "popen-result"
    finally:
        _CURRENT_SCENARIO.reset(token)

    _assert_probe_call(run_calls[0], second_events, ["pkg.mod:second", "pkg.mod:third"])
    _assert_probe_call(popen_calls[0], second_events, ["pkg.mod:second", "pkg.mod:third"])


def test_install_subprocess_probe_rewraps_replaced_launchers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_calls: list[dict[str, object]] = []
    popen_calls: list[dict[str, object]] = []

    def first_run(*args: object, **kwargs: object) -> str:
        return "first-run"

    def first_popen(*args: object, **kwargs: object) -> str:
        return "first-popen"

    def replacement_run(*args: object, **kwargs: object) -> str:
        run_calls.append({"args": args, "kwargs": kwargs})
        return "replacement-run"

    def replacement_popen(*args: object, **kwargs: object) -> str:
        popen_calls.append({"args": args, "kwargs": kwargs})
        return "replacement-popen"

    events = tmp_path / "events.jsonl"

    monkeypatch.setattr(trace_mod, "_PATCHED_RUN", None)
    monkeypatch.setattr(trace_mod, "_PATCHED_POPEN", None)
    monkeypatch.setattr(trace_mod.subprocess, "run", first_run)
    monkeypatch.setattr(trace_mod.subprocess, "Popen", first_popen)

    _install_subprocess_probe(("pkg.mod:first",), tmp_path / "first.jsonl")
    stale_run_wrapper = trace_mod.subprocess.run
    stale_popen_wrapper = trace_mod.subprocess.Popen

    monkeypatch.setattr(trace_mod.subprocess, "run", replacement_run)
    monkeypatch.setattr(trace_mod.subprocess, "Popen", replacement_popen)

    _install_subprocess_probe(("pkg.mod:replacement",), events)

    assert trace_mod.subprocess.run is trace_mod._PATCHED_RUN
    assert trace_mod.subprocess.Popen is trace_mod._PATCHED_POPEN
    assert trace_mod.subprocess.run is not stale_run_wrapper
    assert trace_mod.subprocess.Popen is not stale_popen_wrapper

    token = _CURRENT_SCENARIO.set((tmp_path / "feature.feature", 4))
    try:
        assert trace_mod.subprocess.run([sys.executable, "-m", "sample"]) == "replacement-run"
        assert trace_mod.subprocess.Popen([sys.executable, "-m", "sample"]) == "replacement-popen"
    finally:
        _CURRENT_SCENARIO.reset(token)

    _assert_probe_call(run_calls[0], events, ["pkg.mod:replacement"])
    _assert_probe_call(popen_calls[0], events, ["pkg.mod:replacement"])


def test_subprocess_command_supports_kwargs_and_command_detection() -> None:
    assert _supports_python_sitecustomize([sys.executable, "-m", "pytest"])
    assert not _supports_python_sitecustomize(["git", "status"])
    assert not _supports_python_sitecustomize("python -m pytest")


def test_current_scenario_payload_prefers_context_over_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(SCENARIO_ENV, "stale")
    scenario_key = (tmp_path / "feature.feature", 9)
    token = _CURRENT_SCENARIO.set(scenario_key)
    try:
        assert _current_scenario_payload() == _encode_scenario_key(scenario_key)
    finally:
        _CURRENT_SCENARIO.reset(token)
    assert _current_scenario_payload() == "stale"


def test_decode_and_parse_event_reject_malformed_values(tmp_path: Path) -> None:
    assert _decode_scenario_key("not-json") is None
    assert _decode_scenario_key(json.dumps({"feature_path": 1, "scenario_line": "x"})) is None
    assert _parse_subprocess_event("not-json") is None
    assert _parse_subprocess_event(json.dumps([])) is None
    assert _parse_subprocess_event(json.dumps({"scenario": "{}", "symbol": 1})) is None
    malformed_scenario = json.dumps({"feature_path": 1, "scenario_line": 2})
    assert (
        _parse_subprocess_event(json.dumps({"scenario": malformed_scenario, "symbol": "x"}))
        is None
    )


def test_merge_subprocess_events_ignores_missing_file(tmp_path: Path) -> None:
    reached: dict[tuple[Path, int], set[str]] = {}

    _merge_subprocess_events(tmp_path / "missing.jsonl", reached)

    assert reached == {}


def test_scenario_line_falls_back_to_zero() -> None:
    assert _scenario_line(object()) == 0


def test_scenario_line_prefers_line_number_over_line() -> None:
    scenario = SimpleNamespace(line_number=3, line=9)

    assert _scenario_line(scenario) == 3


def test_scenario_line_rejects_boolean_line_number_before_line_fallback() -> None:
    assert _scenario_line(SimpleNamespace(line_number=True, line=8)) == 8
    assert _scenario_line(SimpleNamespace(line_number=True, line=False)) == 0


def test_write_reached_events_skips_empty_and_writes_sorted(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"

    _write_reached_events(path, "scenario", set())
    _write_reached_events(path, "scenario", {"pkg.mod:b", "pkg.mod:a"})

    assert path.read_text(encoding="utf-8").splitlines() == [
        json.dumps({"scenario": "scenario", "symbol": "pkg.mod:a"}),
        json.dumps({"scenario": "scenario", "symbol": "pkg.mod:b"}),
    ]


def test_record_current_process_events_flushes_reached_symbols_from_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events = tmp_path / "events.jsonl"
    scenario = _encode_scenario_key((tmp_path / "feature.feature", 4))
    registered: list[object] = []
    traces: list[object] = []
    monkeypatch.setenv(SCENARIO_ENV, scenario)
    monkeypatch.setenv(EVENTS_ENV, str(events))
    monkeypatch.setenv(PAYLOAD_ENV, json.dumps({"public_symbols": ["pkg.mod:tracked"]}))

    def register(callback: object) -> None:
        registered.append(callback)

    def gettrace() -> str:
        return "previous-trace"

    def settrace(trace: object) -> None:
        traces.append(trace)

    monkeypatch.setattr(trace_mod.atexit, "register", register)
    monkeypatch.setattr(trace_mod.sys, "gettrace", gettrace)
    monkeypatch.setattr(trace_mod.sys, "settrace", settrace)

    _record_current_process_events()

    assert len(registered) == 1
    trace = traces[0]
    assert callable(trace)
    trace(_frame("tracked", {"__name__": "pkg.mod"}), "call", None)
    flush = registered[0]
    assert callable(flush)
    flush()

    assert traces[-1] == "previous-trace"
    assert events.read_text(encoding="utf-8").splitlines() == [
        json.dumps({"scenario": scenario, "symbol": "pkg.mod:tracked"})
    ]


def test_subprocess_tracer_records_symbol() -> None:
    reached: set[str] = set()
    trace = _tracer_for_subprocess(("pkg.mod:foo",), reached)

    trace(_frame("foo", {"__name__": "pkg.mod"}), "call", None)

    assert reached == {"pkg.mod:foo"}


def test_subprocess_tracer_ignores_non_matches() -> None:
    reached: set[str] = set()
    trace = _tracer_for_subprocess(("pkg.mod:foo",), reached)

    trace(_frame("foo", {"__name__": "pkg.mod"}), "line", None)
    trace(_frame("bar", {"__name__": "pkg.mod"}), "call", None)
    trace(_frame("foo", {"__name__": "other.mod"}), "call", None)

    assert reached == set()
