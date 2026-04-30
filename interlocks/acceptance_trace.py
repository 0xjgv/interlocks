"""Advisory acceptance trace evidence."""

from __future__ import annotations

import json
import os
import runpy
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from interlocks.runner import python_m

_TRACE_ENV = "INTERLOCKS_ACCEPTANCE_TRACE"
_IN_PROCESS_ENV = "INTERLOCKS_ACCEPTANCE_TRACE_IN_PROCESS"
_FAILURE_ENV = "INTERLOCKS_ACCEPTANCE_TRACE_FAIL"
_DEFAULT_TRACE_PATH = Path(".interlocks/acceptance-trace.json")


@dataclass(frozen=True, order=True)
class TraceSymbolEvidence:
    symbol: str
    reached: bool


@dataclass(frozen=True)
class AcceptanceTraceEvidence:
    symbols: tuple[TraceSymbolEvidence, ...]
    failure: str | None = None

    @property
    def reached_symbols(self) -> tuple[str, ...]:
        return tuple(symbol.symbol for symbol in self.symbols if symbol.reached)

    @property
    def unreached_symbols(self) -> tuple[str, ...]:
        return tuple(symbol.symbol for symbol in self.symbols if not symbol.reached)


def trace_evidence_path(project_root: Path) -> Path:
    return project_root / _DEFAULT_TRACE_PATH


def trace_enabled() -> bool:
    return os.environ.get(_TRACE_ENV) == "1"


def trace_can_wrap_command(runner_cmd: list[str]) -> bool:
    return os.environ.get(_IN_PROCESS_ENV) == "1" and _runner_module(runner_cmd) is not None


def trace_wrapper_cmd(
    project_root: Path, public_symbols: tuple[str, ...], runner_cmd: list[str]
) -> list[str]:
    payload = {
        "project_root": str(project_root),
        "public_symbols": list(public_symbols),
        "runner_cmd": runner_cmd,
    }
    return python_m("interlocks.acceptance_trace", json.dumps(payload))


def load_trace_evidence(project_root: Path) -> AcceptanceTraceEvidence | None:
    path = trace_evidence_path(project_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    failure = data.get("failure")
    raw_symbols = data.get("symbols")
    if not isinstance(raw_symbols, list):
        return None
    symbols: list[TraceSymbolEvidence] = []
    for item in raw_symbols:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol")
        reached = item.get("reached")
        if isinstance(symbol, str) and isinstance(reached, bool):
            symbols.append(TraceSymbolEvidence(symbol, reached))
    return AcceptanceTraceEvidence(
        tuple(sorted(symbols)), failure if isinstance(failure, str) else None
    )


def format_trace_evidence(evidence: AcceptanceTraceEvidence | None) -> str:
    if evidence is None:
        return (
            "acceptance trace evidence unavailable — run acceptance with "
            "INTERLOCKS_ACCEPTANCE_TRACE=1 for advisory runtime detail"
        )
    lines = ["acceptance trace evidence (advisory; not blocking)"]
    if evidence.failure is not None:
        lines.append(f"trace instrumentation failed: {evidence.failure}")
    if evidence.reached_symbols:
        lines.append("reached public symbols: " + ", ".join(evidence.reached_symbols))
    if evidence.unreached_symbols:
        lines.append("unreached public symbols: " + ", ".join(evidence.unreached_symbols))
    return "\n".join(lines)


def collect_trace_evidence(
    project_root: Path,
    public_symbols: tuple[str, ...],
    runner_cmd: list[str],
) -> int:
    reached: set[str] = set()
    failure: str | None = None
    previous_trace = sys.gettrace()
    try:
        if os.environ.get(_FAILURE_ENV) == "1":
            raise RuntimeError("forced trace instrumentation failure")
        sys.settrace(_tracer(public_symbols, reached))
    except Exception as exc:
        failure = str(exc) or exc.__class__.__name__
    try:
        returncode = _run_runner(runner_cmd)
    except Exception as exc:
        failure = failure or str(exc) or exc.__class__.__name__
        returncode = 1
    finally:
        sys.settrace(previous_trace)
        _write_trace_evidence(project_root, public_symbols, reached, failure)
    return returncode


def _tracer(public_symbols: tuple[str, ...], reached: set[str]) -> Any:
    symbol_index = symbols_by_function(public_symbols)

    def trace(frame: Any, event: str, _arg: object) -> Any:
        if event != "call":
            return trace
        candidates = symbol_index.get(frame.f_code.co_name)
        if not candidates:
            return trace
        for module in frame_module_names(frame):
            symbol = candidates.get(module)
            if symbol is not None:
                reached.add(symbol)
                break
        return trace

    return trace


def frame_module_names(frame: Any) -> tuple[str, ...]:
    names: list[str] = []
    module = frame.f_globals.get("__name__")
    if isinstance(module, str):
        names.append(module)
    spec = frame.f_globals.get("__spec__")
    spec_name = getattr(spec, "name", None)
    if isinstance(spec_name, str):
        names.append(spec_name)
    return tuple(dict.fromkeys(names))


def symbols_by_function(public_symbols: tuple[str, ...]) -> dict[str, dict[str, str]]:
    grouped: dict[str, dict[str, str]] = {}
    for symbol in public_symbols:
        module, separator, function = symbol.rpartition(":")
        if separator:
            grouped.setdefault(function, {})[module] = symbol
    return grouped


def _run_runner(runner_cmd: list[str]) -> int:
    module = _runner_module(runner_cmd)
    if module is None:
        return 1
    old_argv = sys.argv[:]
    sys.argv = [module, *runner_cmd[3:]]
    try:
        return _run_module(module)
    finally:
        sys.argv = old_argv


def _runner_module(runner_cmd: list[str]) -> str | None:
    if len(runner_cmd) < 3 or runner_cmd[1] != "-m":
        return None
    return runner_cmd[2]


def _run_module(module: str) -> int:
    try:
        runpy.run_module(module, run_name="__main__", alter_sys=True)
        return 0
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1


def _write_trace_evidence(
    project_root: Path,
    public_symbols: tuple[str, ...],
    reached: set[str],
    failure: str | None,
) -> None:
    path = trace_evidence_path(project_root)
    payload = {
        "failure": failure,
        "symbols": [
            {"symbol": symbol, "reached": symbol in reached} for symbol in sorted(public_symbols)
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    try:
        payload = json.loads(sys.argv[1])
        project_root = Path(payload["project_root"])
        public_symbols = tuple(str(symbol) for symbol in payload["public_symbols"])
        runner_cmd = [str(arg) for arg in payload["runner_cmd"]]
    except (IndexError, KeyError, TypeError, json.JSONDecodeError):
        sys.exit(1)
    sys.exit(collect_trace_evidence(project_root, public_symbols, runner_cmd))


if __name__ == "__main__":
    main()
