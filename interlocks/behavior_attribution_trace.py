"""pytest-bdd plugin that records behavior attribution evidence."""

from __future__ import annotations

import atexit
import contextvars
import json
import os
import subprocess  # noqa: S404
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from interlocks.acceptance_trace import frame_module_names, symbols_by_function
from interlocks.behavior_attribution import write_evidence

PAYLOAD_ENV = "INTERLOCKS_BEHAVIOR_ATTRIBUTION_PAYLOAD"
SCENARIO_ENV = "INTERLOCKS_BEHAVIOR_ATTRIBUTION_SCENARIO"
EVENTS_ENV = "INTERLOCKS_BEHAVIOR_ATTRIBUTION_EVENTS"
PLUGIN_NAME = "interlocks.behavior_attribution_trace"

_CURRENT_SCENARIO: contextvars.ContextVar[tuple[Path, int] | None] = contextvars.ContextVar(
    "interlocks_current_scenario",
    default=None,
)
_PREVIOUS_SCENARIO_ENV: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "interlocks_previous_scenario_env",
    default=None,
)
_REACHED: dict[tuple[Path, int], set[str]] = {}
_EVIDENCE_PATH: Path | None = None
_EVENTS_PATH: Path | None = None
_PREVIOUS_TRACE: Any = None
_FAILURE: str | None = None
_PATCHED_RUN: Callable[..., Any] | None = None


def pytest_configure(config: object) -> None:
    global _EVIDENCE_PATH, _EVENTS_PATH, _PREVIOUS_TRACE, _FAILURE, _REACHED  # noqa: PLW0603
    _REACHED = {}
    try:
        payload = json.loads(_payload_text(config))
        public_symbols = tuple(str(symbol) for symbol in payload["public_symbols"])
        _EVIDENCE_PATH = Path(str(payload["evidence_path"]))
        _EVENTS_PATH = _events_path(_EVIDENCE_PATH)
        _EVENTS_PATH.unlink(missing_ok=True)
    except Exception as exc:
        _FAILURE = str(exc) or exc.__class__.__name__
        return
    _install_subprocess_probe(public_symbols, _EVENTS_PATH)
    _PREVIOUS_TRACE = sys.gettrace()
    sys.settrace(_tracer(public_symbols, _REACHED))


def pytest_bdd_before_scenario(
    request: object,  # noqa: ARG001
    feature: object,
    scenario: object,
) -> None:
    key = (_feature_path(feature), _scenario_line(scenario))
    _REACHED.setdefault(key, set())
    _CURRENT_SCENARIO.set(key)
    _PREVIOUS_SCENARIO_ENV.set(os.environ.get(SCENARIO_ENV))
    os.environ[SCENARIO_ENV] = _encode_scenario_key(key)


def pytest_bdd_after_scenario(
    request: object,  # noqa: ARG001
    feature: object,  # noqa: ARG001
    scenario: object,  # noqa: ARG001
) -> None:
    _CURRENT_SCENARIO.set(None)
    previous = _PREVIOUS_SCENARIO_ENV.get()
    if previous is None:
        os.environ.pop(SCENARIO_ENV, None)
    else:
        os.environ[SCENARIO_ENV] = previous


def pytest_sessionfinish(session: object, exitstatus: int) -> None:  # noqa: ARG001
    global _PREVIOUS_TRACE  # noqa: PLW0603
    if _PREVIOUS_TRACE is not None:
        sys.settrace(_PREVIOUS_TRACE)
        _PREVIOUS_TRACE = None
    if _EVENTS_PATH is not None:
        _merge_subprocess_events(_EVENTS_PATH, _REACHED)
    if _EVIDENCE_PATH is None:
        return
    write_evidence(
        _EVIDENCE_PATH,
        reached_by_scenario=_REACHED,
        created_at=time.time(),
        failure=_FAILURE,
    )


def _payload_text(config: object) -> str:
    config_getoption = getattr(config, "getoption", None)
    if callable(config_getoption):
        option = config_getoption(PAYLOAD_ENV, default=None)
        if isinstance(option, str):
            return option
    return os.environ[PAYLOAD_ENV]


def _tracer(
    public_symbols: tuple[str, ...],
    reached_by_scenario: dict[tuple[Path, int], set[str]],
) -> Any:
    symbol_index = symbols_by_function(public_symbols)

    def trace(frame: Any, event: str, _arg: object) -> Any:
        key = _CURRENT_SCENARIO.get()
        if key is None:
            return trace
        symbol = _matched_symbol(frame, event, symbol_index)
        if symbol is not None:
            reached_by_scenario.setdefault(key, set()).add(symbol)
        return trace

    return trace


def _install_subprocess_probe(public_symbols: tuple[str, ...], events_path: Path | None) -> None:
    global _PATCHED_RUN  # noqa: PLW0603
    if events_path is None:
        return
    if _PATCHED_RUN is None or subprocess.run is not _PATCHED_RUN:
        _PATCHED_RUN = _subprocess_run_probe(subprocess.run, public_symbols, events_path)
        subprocess.run = _PATCHED_RUN  # type: ignore[method-assign]
        return
    _set_probe(public_symbols, events_path)


def _subprocess_run_probe(
    original_run: Callable[..., Any],
    public_symbols: tuple[str, ...],
    events_path: Path,
) -> Callable[..., Any]:
    state = _set_probe(public_symbols, events_path)

    def run(*args: Any, **kwargs: Any) -> Any:
        command = _subprocess_command(args, kwargs)
        if not _supports_python_sitecustomize(command):
            return original_run(*args, **kwargs)
        public_symbols = state.get("public_symbols")
        events_path = state.get("events_path")
        if not isinstance(public_symbols, tuple) or not isinstance(events_path, Path):
            return original_run(*args, **kwargs)
        env = _probe_env(kwargs.get("env"), public_symbols, events_path)
        if env is not None:
            kwargs["env"] = env
        return original_run(*args, **kwargs)

    run._interlocks_behavior_attribution_probe = state  # type: ignore[attr-defined]
    return run


def _set_probe(public_symbols: tuple[str, ...], events_path: Path) -> dict[str, object]:
    existing = getattr(_PATCHED_RUN, "_interlocks_behavior_attribution_probe", None)
    state: dict[str, object] = existing if isinstance(existing, dict) else {}
    state["public_symbols"] = public_symbols
    state["events_path"] = events_path
    return state


def _subprocess_command(args: tuple[Any, ...], kwargs: dict[str, Any]) -> object:
    if args:
        return args[0]
    return kwargs.get("args")


def _current_scenario_payload() -> str | None:
    key = _CURRENT_SCENARIO.get()
    if key is not None:
        return _encode_scenario_key(key)
    return os.environ.get(SCENARIO_ENV)


def _probe_env(
    explicit_env: object,
    public_symbols: tuple[str, ...],
    events_path: Path,
) -> dict[str, str] | None:
    scenario = _current_scenario_payload()
    if scenario is None:
        return None
    base = os.environ if explicit_env is None else explicit_env
    if not isinstance(base, Mapping):
        return None
    env = {str(key): str(value) for key, value in base.items()}
    env[SCENARIO_ENV] = scenario
    env[EVENTS_ENV] = str(events_path)
    env[PAYLOAD_ENV] = json.dumps({"public_symbols": list(public_symbols)})
    _install_sitecustomize(events_path.parent)
    env["PYTHONPATH"] = _prepend_pythonpath(events_path.parent, env.get("PYTHONPATH"))
    return env


def _supports_python_sitecustomize(command: object) -> bool:
    if not isinstance(command, list | tuple) or not command:
        return False
    executable = str(command[0])
    return Path(executable).name.startswith("python")


def _install_sitecustomize(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    sitecustomize = directory / "sitecustomize.py"
    content = "import interlocks.behavior_attribution_trace\n"
    try:
        current = sitecustomize.read_text(encoding="utf-8")
    except OSError:
        current = None
    if current == content:
        return
    sitecustomize.write_text(content, encoding="utf-8")


def _prepend_pythonpath(path: Path, current: str | None) -> str:
    if not current:
        return str(path)
    return f"{path}{os.pathsep}{current}"


def _events_path(evidence_path: Path) -> Path:
    return evidence_path.with_name(f"{evidence_path.name}.events")


def _feature_path(feature: object) -> Path:
    filename = getattr(feature, "filename", None)
    return Path(str(filename)).resolve()


def _scenario_line(scenario: object) -> int:
    for attr in ("line_number", "line"):
        value = getattr(scenario, attr, None)
        if isinstance(value, int):
            return value
    return 0


def _matched_symbol(frame: Any, event: str, symbol_index: dict[str, dict[str, str]]) -> str | None:
    if event != "call" or frame.f_globals is None:
        return None
    candidates = symbol_index.get(frame.f_code.co_name)
    if not candidates:
        return None
    for module in frame_module_names(frame):
        symbol = candidates.get(module)
        if symbol is not None:
            return symbol
    return None


def _encode_scenario_key(key: tuple[Path, int]) -> str:
    feature_path, scenario_line = key
    return json.dumps({"feature_path": str(feature_path), "scenario_line": scenario_line})


def _decode_scenario_key(raw: str) -> tuple[Path, int] | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    feature_path = data.get("feature_path") if isinstance(data, dict) else None
    scenario_line = data.get("scenario_line") if isinstance(data, dict) else None
    if not isinstance(feature_path, str) or not isinstance(scenario_line, int):
        return None
    return (Path(feature_path), scenario_line)


def _merge_subprocess_events(
    events_path: Path,
    reached_by_scenario: dict[tuple[Path, int], set[str]],
) -> None:
    try:
        with events_path.open(encoding="utf-8") as stream:
            for line in stream:
                event = _parse_subprocess_event(line)
                if event is None:
                    continue
                key, symbol = event
                reached_by_scenario.setdefault(key, set()).add(symbol)
    except OSError:
        return


def _parse_subprocess_event(line: str) -> tuple[tuple[Path, int], str] | None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    symbol = data.get("symbol")
    raw_scenario = data.get("scenario")
    if not isinstance(symbol, str) or not isinstance(raw_scenario, str):
        return None
    key = _decode_scenario_key(raw_scenario)
    if key is None:
        return None
    return key, symbol


def _write_reached_events(path: Path, scenario: str, reached: set[str]) -> None:
    if not reached:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for symbol in sorted(reached):
            stream.write(json.dumps({"scenario": scenario, "symbol": symbol}) + "\n")


def _record_current_process_events() -> None:
    scenario = os.environ.get(SCENARIO_ENV)
    events = os.environ.get(EVENTS_ENV)
    payload = os.environ.get(PAYLOAD_ENV)
    if scenario is None or events is None or payload is None:
        return
    try:
        public_symbols = tuple(str(symbol) for symbol in json.loads(payload)["public_symbols"])
    except Exception:
        return
    reached: set[str] = set()
    previous_trace = sys.gettrace()
    sys.settrace(_tracer_for_subprocess(public_symbols, reached))

    def flush() -> None:
        sys.settrace(previous_trace)
        _write_reached_events(Path(events), scenario, reached)

    atexit.register(flush)


def _tracer_for_subprocess(public_symbols: tuple[str, ...], reached: set[str]) -> Any:
    symbol_index = symbols_by_function(public_symbols)

    def trace(frame: Any, event: str, _arg: object) -> Any:
        symbol = _matched_symbol(frame, event, symbol_index)
        if symbol is not None:
            reached.add(symbol)
        return trace

    return trace


_record_current_process_events()
