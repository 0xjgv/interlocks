"""Property tests for acceptance trace symbol matching."""

from __future__ import annotations

from types import SimpleNamespace

from hypothesis import given
from hypothesis import strategies as st

from interlocks.acceptance_trace import (
    _match_public_symbol,
    _runner_module,
    _tracer,
    format_trace_evidence,
    symbols_by_function,
)

_IDENT = st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,20}", fullmatch=True)
_MODULES = st.lists(_IDENT, min_size=1, max_size=4).map(".".join)
_SYMBOLS = st.builds(lambda module, function: f"{module}:{function}", _MODULES, _IDENT)


def _frame(function: str, module: str, spec_name: str | None = None) -> SimpleNamespace:
    spec = None if spec_name is None else SimpleNamespace(name=spec_name)
    return SimpleNamespace(
        f_code=SimpleNamespace(co_name=function),
        f_globals={"__name__": module, "__spec__": spec},
    )


@given(st.lists(_SYMBOLS, unique=True, max_size=20))
def test_symbols_by_function_indexes_well_formed_symbols(symbols: list[str]) -> None:
    index = symbols_by_function(tuple(symbols))

    for symbol in symbols:
        module, _separator, function = symbol.rpartition(":")
        assert index[function][module] == symbol


@given(module=_MODULES, function=_IDENT)
def test_match_public_symbol_matches_call_event(module: str, function: str) -> None:
    symbol = f"{module}:{function}"
    index = symbols_by_function((symbol,))

    assert _match_public_symbol(_frame(function, module), "call", index) == symbol


@given(module=_MODULES, function=_IDENT, event=st.text().filter(lambda value: value != "call"))
def test_match_public_symbol_ignores_non_call_events(
    module: str,
    function: str,
    event: str,
) -> None:
    symbol = f"{module}:{function}"
    index = symbols_by_function((symbol,))

    assert _match_public_symbol(_frame(function, module), event, index) is None


@given(module=_MODULES, spec_name=_MODULES, function=_IDENT)
def test_match_public_symbol_uses_spec_name_alias(
    module: str,
    spec_name: str,
    function: str,
) -> None:
    symbol = f"{spec_name}:{function}"
    index = symbols_by_function((symbol,))

    assert _match_public_symbol(_frame(function, module, spec_name), "call", index) == symbol


@given(module=_MODULES, function=_IDENT)
def test_tracer_records_matching_call_frame_and_returns_itself(module: str, function: str) -> None:
    reached: set[str] = set()
    symbol = f"{module}:{function}"

    trace = _tracer((symbol,), reached)
    returned = trace(_frame(function, module), "call", None)

    assert returned is trace
    assert reached == {symbol}


@given(st.none())
def test_missing_trace_evidence_message_is_stable(evidence: None) -> None:
    assert "advisory runtime detail" in format_trace_evidence(evidence)


@given(cmd=st.lists(st.text(max_size=30), max_size=8))
def test_runner_module_extracts_only_python_module_commands(cmd: list[str]) -> None:
    expected = cmd[2] if len(cmd) >= 3 and cmd[1] == "-m" else None

    assert _runner_module(cmd) == expected
