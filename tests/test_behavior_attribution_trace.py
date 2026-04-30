from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

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
    _scenario_line,
    _supports_python_sitecustomize,
    _tracer,
    _tracer_for_subprocess,
    _write_reached_events,
)


def _frame(name: str, globals_: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(f_code=SimpleNamespace(co_name=name), f_globals=globals_)


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
        result = subprocess.run(["git", "status"], check=False)  # noqa: S607
    finally:
        _CURRENT_SCENARIO.reset(token)

    assert result == "done"
    kwargs = calls[0]["kwargs"]
    assert isinstance(kwargs, dict)
    assert "env" not in kwargs


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


def test_write_reached_events_skips_empty_and_writes_sorted(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"

    _write_reached_events(path, "scenario", set())
    _write_reached_events(path, "scenario", {"pkg.mod:b", "pkg.mod:a"})

    assert path.read_text(encoding="utf-8").splitlines() == [
        json.dumps({"scenario": "scenario", "symbol": "pkg.mod:a"}),
        json.dumps({"scenario": "scenario", "symbol": "pkg.mod:b"}),
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
