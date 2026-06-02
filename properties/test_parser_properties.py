"""Property tests for parser-style hardening candidates."""

from __future__ import annotations

import json
import string
from pathlib import Path
from types import SimpleNamespace

from hypothesis import given
from hypothesis import strategies as st

from interlocks.behavior_attribution_trace import (
    _CURRENT_SCENARIO,
    _decode_scenario_key,
    _encode_scenario_key,
    _loads_dict,
    _parse_subprocess_event,
    _scenario_line,
    _subprocess_command,
    _supports_python_sitecustomize,
    _tracer,
    _tracer_for_subprocess,
)
from interlocks.lintfix.discover import parse_diagnostics
from interlocks.reports.suppressions import _parse_line_for_suppressions

_JSON_VALUE = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(min_value=-1_000_000, max_value=1_000_000)
    | st.text(max_size=40),
    lambda children: (
        st.lists(children, max_size=4)
        | st.dictionaries(st.text(max_size=20), children, max_size=4)
    ),
    max_leaves=12,
)
_RUFF_RULE_CODES = st.text(
    alphabet=string.ascii_uppercase + string.digits,
    min_size=2,
    max_size=8,
).filter(lambda value: value[0].isalpha() and value[-1].isdigit())
_PY_IDENTIFIER = st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,20}", fullmatch=True)
_MODULE = st.lists(_PY_IDENTIFIER, min_size=1, max_size=4).map(".".join)


def _frame(module: str, function: str) -> SimpleNamespace:
    return SimpleNamespace(
        f_code=SimpleNamespace(co_name=function), f_globals={"__name__": module}
    )


@given(st.text())
def test_json_object_loader_matches_json_object_contract(raw: str) -> None:
    loaded = _loads_dict(raw)

    try:
        expected = json.loads(raw)
    except json.JSONDecodeError:
        assert loaded is None
        return
    if isinstance(expected, dict):
        assert loaded == expected
    else:
        assert loaded is None


@given(payload=st.dictionaries(st.text(max_size=20), _JSON_VALUE, max_size=8))
def test_json_object_loader_round_trips_objects(payload: dict[str, object]) -> None:
    assert _loads_dict(json.dumps(payload)) == payload


@given(
    payload=st.one_of(st.none(), st.booleans(), st.integers(), st.text(), st.lists(_JSON_VALUE))
)
def test_json_object_loader_rejects_valid_non_object_json(payload: object) -> None:
    assert _loads_dict(json.dumps(payload)) is None


@given(st.text())
def test_subprocess_event_parser_never_raises(line: str) -> None:
    event = _parse_subprocess_event(line)
    assert event is None or isinstance(event[1], str)


@given(
    feature_path=st.text(min_size=1),
    scenario_line=st.integers(min_value=1, max_value=1_000_000),
    symbol=st.text(min_size=1),
)
def test_subprocess_event_parser_accepts_encoded_scenario(
    feature_path: str, scenario_line: int, symbol: str
) -> None:
    scenario = _encode_scenario_key((Path(feature_path), scenario_line))
    payload = json.dumps({"scenario": scenario, "symbol": symbol})

    event = _parse_subprocess_event(payload)

    assert event == ((Path(feature_path), scenario_line), symbol)


@given(feature_path=_JSON_VALUE, scenario_line=_JSON_VALUE)
def test_decode_scenario_key_accepts_only_string_path_and_positive_int_line(
    feature_path: object,
    scenario_line: object,
) -> None:
    raw = json.dumps({"feature_path": feature_path, "scenario_line": scenario_line})

    decoded = _decode_scenario_key(raw)

    if (
        isinstance(feature_path, str)
        and isinstance(scenario_line, int)
        and not isinstance(scenario_line, bool)
        and scenario_line > 0
    ):
        assert decoded == (Path(feature_path), scenario_line)
    else:
        assert decoded is None


@given(
    feature_path=st.text(min_size=1, max_size=80),
    scenario_line=st.integers(min_value=1, max_value=1_000_000),
)
def test_decode_scenario_key_round_trips_encoded_keys(
    feature_path: str,
    scenario_line: int,
) -> None:
    encoded = _encode_scenario_key((Path(feature_path), scenario_line))

    assert _decode_scenario_key(encoded) == (Path(feature_path), scenario_line)


@given(raw=st.text().filter(lambda value: not value.strip().startswith("{")))
def test_decode_scenario_key_rejects_non_object_json(raw: str) -> None:
    assert _decode_scenario_key(raw) is None


@given(
    line_number=st.one_of(st.booleans(), st.integers(min_value=-10, max_value=10), st.none()),
    line=st.one_of(st.booleans(), st.integers(min_value=-10, max_value=10), st.none()),
)
def test_scenario_line_accepts_only_positive_non_boolean_int_attrs(
    line_number: object,
    line: object,
) -> None:
    scenario = SimpleNamespace(line_number=line_number, line=line)

    parsed = _scenario_line(scenario)

    for value in (line_number, line):
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            assert parsed == value
            return
    assert parsed == 0


@given(
    args=st.lists(_JSON_VALUE, max_size=5),
    kw_args=st.one_of(st.none(), _JSON_VALUE),
)
def test_subprocess_command_uses_first_positional_before_kwargs(
    args: list[object],
    kw_args: object,
) -> None:
    kwargs = {} if kw_args is None else {"args": kw_args}

    command = _subprocess_command(tuple(args), kwargs)

    assert command == (args[0] if args else kw_args)


@given(kwargs=st.dictionaries(st.text(max_size=20), _JSON_VALUE, max_size=5))
def test_subprocess_command_returns_none_without_positional_or_args_keyword(
    kwargs: dict[str, object],
) -> None:
    kwargs.pop("args", None)

    assert _subprocess_command((), kwargs) is None


@given(command=st.one_of(st.none(), st.text(max_size=30), st.lists(st.text(max_size=30))))
def test_supports_python_sitecustomize_matches_python_executable_names(command: object) -> None:
    supported = _supports_python_sitecustomize(command)

    if isinstance(command, list) and command:
        assert supported is Path(str(command[0])).name.startswith("python")
    else:
        assert supported is False


@given(module=_MODULE, function=_PY_IDENTIFIER, line=st.integers(min_value=1, max_value=1_000))
def test_tracer_records_matching_public_symbol_for_current_scenario(
    module: str,
    function: str,
    line: int,
) -> None:
    reached: dict[tuple[Path, int], set[str]] = {}
    scenario = (Path("generated.feature"), line)
    symbol = f"{module}:{function}"
    token = _CURRENT_SCENARIO.set(scenario)
    try:
        trace = _tracer((symbol,), reached)
        returned = trace(_frame(module, function), "call", None)
    finally:
        _CURRENT_SCENARIO.reset(token)

    assert returned is trace
    assert reached == {scenario: {symbol}}


@given(module=_MODULE, function=_PY_IDENTIFIER)
def test_tracer_ignores_matching_public_symbol_without_current_scenario(
    module: str,
    function: str,
) -> None:
    reached: dict[tuple[Path, int], set[str]] = {}
    symbol = f"{module}:{function}"
    trace = _tracer((symbol,), reached)

    returned = trace(_frame(module, function), "call", None)

    assert returned is trace
    assert reached == {}


@given(
    module=_MODULE,
    function=_PY_IDENTIFIER,
    line=st.integers(min_value=1, max_value=1_000),
    event=st.text().filter(lambda value: value != "call"),
)
def test_tracer_ignores_non_call_events_for_current_scenario(
    module: str,
    function: str,
    line: int,
    event: str,
) -> None:
    reached: dict[tuple[Path, int], set[str]] = {}
    scenario = (Path("generated.feature"), line)
    symbol = f"{module}:{function}"
    token = _CURRENT_SCENARIO.set(scenario)
    try:
        trace = _tracer((symbol,), reached)
        returned = trace(_frame(module, function), event, None)
    finally:
        _CURRENT_SCENARIO.reset(token)

    assert returned is trace
    assert reached == {}


@given(module=_MODULE, function=_PY_IDENTIFIER)
def test_subprocess_tracer_records_matching_public_symbol(module: str, function: str) -> None:
    reached: set[str] = set()
    symbol = f"{module}:{function}"
    trace = _tracer_for_subprocess((symbol,), reached)

    returned = trace(_frame(module, function), "call", None)

    assert returned is trace
    assert reached == {symbol}


@given(module=_MODULE, function=_PY_IDENTIFIER)
def test_subprocess_tracer_without_public_symbols_never_records_reached_symbols(
    module: str,
    function: str,
) -> None:
    reached: set[str] = set()
    trace = _tracer_for_subprocess((), reached)

    returned = trace(_frame(module, function), "call", None)

    assert returned is trace
    assert reached == set()


@given(scenario_line=st.one_of(st.booleans(), st.integers(max_value=0)))
def test_subprocess_event_parser_rejects_impossible_scenario_lines(
    scenario_line: bool | int,
) -> None:
    scenario = json.dumps({
        "feature_path": "features/example.feature",
        "scenario_line": scenario_line,
    })
    payload = json.dumps({"scenario": scenario, "symbol": "pkg:tracked"})

    assert _parse_subprocess_event(payload) is None


@given(st.text())
def test_ruff_diagnostic_parser_never_raises(raw: str) -> None:
    candidates = parse_diagnostics(raw)

    assert all(candidate.rule for candidate in candidates)
    assert all(candidate.diagnostic_count > 0 for candidate in candidates)


@given(
    rule=_RUFF_RULE_CODES,
    filename=st.text(min_size=1, max_size=40),
    applicability=st.sampled_from(["safe", "unsafe", "unknown"]),
)
def test_ruff_diagnostic_parser_groups_fixable_rules(
    rule: str, filename: str, applicability: str
) -> None:
    raw = json.dumps([
        {"code": rule, "filename": filename, "fix": {"applicability": applicability}},
        {"code": rule, "filename": filename, "fix": {"applicability": "safe"}},
    ])

    [candidate] = parse_diagnostics(raw)

    assert candidate.rule == rule
    assert candidate.files == (filename,)
    assert candidate.diagnostic_count == 2
    assert candidate.has_safe_fix is True
    assert candidate.has_unsafe_fix is (applicability == "unsafe")


@given(st.text())
def test_suppression_line_parser_never_raises(line: str) -> None:
    matches = _parse_line_for_suppressions(line)

    assert all(kind in {"noqa", "type_ignore", "pyright_ignore"} for kind, _rules in matches)
    assert all(rule == rule.strip() and rule for _kind, rules in matches for rule in rules)
