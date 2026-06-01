"""Property tests for behavior-attribution validation."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

from hypothesis import given
from hypothesis import strategies as st

from interlocks import behavior_attribution as behavior_attribution_mod
from interlocks.behavior_attribution import (
    AttributionClaimFailure,
    AttributionEvidence,
    AttributionResult,
    ScenarioReach,
    _classify_claims,
    _format_gaps,
    _format_informational,
    _format_mis_attributed,
    _format_unresolved,
    _parse_reach,
    evidence_is_fresh,
    format_attribution_failure,
    load_evidence,
    validate_attribution,
)
from interlocks.behavior_coverage import Behavior, BehaviorRegistry, ScenarioBehavior
from interlocks.tasks import behavior_attribution as behavior_attribution_task

if TYPE_CHECKING:
    from interlocks.config import InterlockConfig

_ID = st.from_regex(r"[a-z][a-z0-9_-]{0,12}", fullmatch=True)
_CLAIM_STATUS = st.sampled_from(["match", "miss", "gap"])


def _behavior(behavior_id: str, public_symbol: str | None) -> Behavior:
    return Behavior(behavior_id, "task", f"summary {behavior_id}", public_symbol)


def _scenario(behavior_id: str, line: int = 3) -> ScenarioBehavior:
    return ScenarioBehavior(behavior_id, Path("features/example.feature"), "example", line)


def _task_cfg() -> InterlockConfig:
    return cast(
        "InterlockConfig",
        SimpleNamespace(
            features_dir=Path("features"),
            project_root=Path(),
        ),
    )


def _payload_cfg(*, enforced: bool, floor: float) -> InterlockConfig:
    return cast(
        "InterlockConfig",
        SimpleNamespace(
            enforce_behavior_attribution=enforced,
            attribution_min_coverage=floor,
        ),
    )


@given(
    resolved=st.integers(min_value=0, max_value=100),
    total=st.integers(min_value=0, max_value=100),
    enforced=st.booleans(),
    floor=st.floats(min_value=0, max_value=1, allow_nan=False),
)
def test_attribution_payload_counts_and_coverage_are_bounded(
    resolved: int,
    total: int,
    enforced: bool,
    floor: float,
) -> None:
    resolved = min(resolved, total)
    result = AttributionResult(resolved_count=resolved, total_count=total)

    payload = behavior_attribution_task._attribution_payload(
        _payload_cfg(enforced=enforced, floor=floor),
        result,
    )

    coverage = payload["coverage"]
    assert isinstance(coverage, dict)
    assert coverage["resolved"] == resolved
    assert coverage["total"] == total
    assert 0.0 <= coverage["pct"] <= 100.0
    assert payload["status"] in {"ok", "warn", "failed"}
    assert isinstance(payload["next_actions"], list)


@given(enforced=st.booleans())
def test_attribution_payload_warns_or_fails_for_incomplete_results(enforced: bool) -> None:
    result = AttributionResult(unresolved_behaviors=(_behavior("task-x", "pkg:x"),), total_count=1)

    payload = behavior_attribution_task._attribution_payload(
        _payload_cfg(enforced=enforced, floor=0.0),
        result,
    )

    assert payload["passed"] is (not enforced)
    assert payload["status"] == ("failed" if enforced else "warn")
    assert payload["next_actions"]


@given(
    complete=st.booleans(),
    has_warnings=st.booleans(),
    passed=st.booleans(),
)
def test_attribution_status_depends_on_passed_completeness_and_warnings(
    complete: bool,
    has_warnings: bool,
    passed: bool,
) -> None:
    result = AttributionResult(
        unresolved_behaviors=() if complete else (_behavior("task-x", "pkg:x"),),
        instrumentation_gaps=(
            (AttributionClaimFailure(_scenario("task-x"), "pkg:x"),) if has_warnings else ()
        ),
    )

    status = behavior_attribution_task._attribution_status(result, passed=passed)

    if not passed:
        assert status == "failed"
    elif not complete or has_warnings:
        assert status == "warn"
    else:
        assert status == "ok"


@given(complete=st.booleans(), has_warnings=st.booleans())
def test_attribution_status_failure_overrides_result_shape(
    complete: bool,
    has_warnings: bool,
) -> None:
    result = AttributionResult(
        unresolved_behaviors=() if complete else (_behavior("task-x", "pkg:x"),),
        instrumentation_gaps=(
            (AttributionClaimFailure(_scenario("task-x"), "pkg:x"),) if has_warnings else ()
        ),
    )

    assert behavior_attribution_task._attribution_status(result, passed=False) == "failed"


@given(status=st.text(max_size=30), floor_failure=st.booleans())
def test_attribution_next_actions_are_empty_only_for_clean_ok(
    status: str, floor_failure: bool
) -> None:
    actions = behavior_attribution_task._attribution_next_actions(
        status, floor_failure=floor_failure
    )

    assert (actions == []) is (status == "ok" and not floor_failure)
    if actions:
        assert "interlocks behavior-attribution" in actions[0]


@given(
    rows=st.lists(
        st.tuples(st.integers(min_value=-10, max_value=10), st.booleans()),
        max_size=8,
    ),
    evidence_exists=st.booleans(),
)
def test_evidence_is_fresh_depends_on_existing_input_mtimes(
    rows: list[tuple[int, bool]],
    evidence_exists: bool,
) -> None:
    base_mtime = 1_700_000_000
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        evidence = root / "behavior-attribution.json"
        if evidence_exists:
            evidence.write_text("{}", encoding="utf-8")
            os.utime(evidence, (base_mtime, base_mtime))
        inputs: list[Path] = []
        for index, (offset, exists) in enumerate(rows):
            path = root / f"input_{index}.py"
            if exists:
                path.write_text("x", encoding="utf-8")
                os.utime(path, (base_mtime + offset, base_mtime + offset))
            inputs.append(path)

        original = behavior_attribution_mod._attribution_inputs
        behavior_attribution_mod._attribution_inputs = lambda _cfg: tuple(inputs)  # type: ignore[assignment]
        try:
            fresh = evidence_is_fresh(object(), evidence)  # type: ignore[arg-type]
        finally:
            behavior_attribution_mod._attribution_inputs = original

    expected_stale = any(offset > 0 and exists for offset, exists in rows)
    assert fresh is (evidence_exists and not expected_stale)


@given(ids=st.lists(_ID, max_size=8, unique=True))
def test_validate_current_project_skips_registry_without_public_symbols(ids: list[str]) -> None:
    registry = BehaviorRegistry(tuple(_behavior(behavior_id, None) for behavior_id in ids))
    with (
        patch.object(
            behavior_attribution_task, "behavior_registry_for_config", return_value=registry
        ),
        patch.object(
            behavior_attribution_task,
            "feature_files",
            side_effect=AssertionError("symbol-less registry should not read feature files"),
        ),
    ):
        result = behavior_attribution_task._validate_current_project(_task_cfg())

    assert result is None


@given(
    ids=st.lists(_ID, min_size=1, max_size=8, unique=True),
    trace_symbols=st.lists(st.text(min_size=1, max_size=30), max_size=8),
    has_trace=st.booleans(),
)
def test_validate_current_project_passes_runtime_and_scenario_evidence_to_core_validator(
    ids: list[str],
    trace_symbols: list[str],
    has_trace: bool,
) -> None:
    cfg = _task_cfg()
    registry = BehaviorRegistry(
        tuple(_behavior(behavior_id, f"pkg:{behavior_id}") for behavior_id in ids)
    )
    features = [Path("features/generated.feature")]
    scenarios = tuple(_scenario(behavior_id, index + 1) for index, behavior_id in enumerate(ids))
    evidence = AttributionEvidence((), created_at=1.0)
    expected_result = AttributionResult((), (), (), (), tuple(sorted(set(trace_symbols))))
    trace = SimpleNamespace(reached_symbols=tuple(trace_symbols)) if has_trace else None

    with (
        patch.object(
            behavior_attribution_task, "behavior_registry_for_config", return_value=registry
        ),
        patch.object(behavior_attribution_task, "feature_files", return_value=features),
        patch.object(
            behavior_attribution_task,
            "evidence_path",
            return_value=Path(".interlocks/evidence.json"),
        ),
        patch.object(behavior_attribution_task, "load_evidence", return_value=evidence),
        patch.object(behavior_attribution_task, "load_trace_evidence", return_value=trace),
        patch.object(
            behavior_attribution_task, "parse_scenario_behaviors", return_value=scenarios
        ),
        patch.object(
            behavior_attribution_task,
            "validate_attribution",
            return_value=expected_result,
        ) as validate,
    ):
        result = behavior_attribution_task._validate_current_project(cfg)

    assert result is expected_result
    validate.assert_called_once_with(
        registry,
        scenarios,
        evidence,
        aggregate_reached_symbols=tuple(trace_symbols) if has_trace else (),
    )


@given(st.lists(_ID, min_size=1, max_size=12, unique=True))
def test_matching_evidence_resolves_claimed_symbol_bearing_behaviors(ids: list[str]) -> None:
    behaviors = tuple(_behavior(behavior_id, f"pkg:{behavior_id}") for behavior_id in ids)
    scenarios = tuple(
        _scenario(behavior_id, line=index + 1) for index, behavior_id in enumerate(ids)
    )
    evidence = AttributionEvidence(
        tuple(
            ScenarioReach(
                scenario.feature_path,
                scenario.scenario_line,
                frozenset({f"pkg:{scenario.behavior_id}"}),
            )
            for scenario in scenarios
        ),
        created_at=1.0,
    )

    result = validate_attribution(BehaviorRegistry(behaviors), scenarios, evidence)

    assert result.is_complete
    assert result.resolved_count == len(ids)
    assert result.total_count == len(ids)
    assert result.coverage_pct == 1.0
    assert result.mis_attributed == ()
    assert result.unresolved_behaviors == ()
    assert result.instrumentation_gaps == ()


@given(st.lists(_ID, min_size=1, max_size=12, unique=True))
def test_missing_evidence_never_resolves_claimed_symbol_bearing_behaviors(
    ids: list[str],
) -> None:
    behaviors = tuple(_behavior(behavior_id, f"pkg:{behavior_id}") for behavior_id in ids)
    scenarios = tuple(
        _scenario(behavior_id, line=index + 1) for index, behavior_id in enumerate(ids)
    )

    result = validate_attribution(BehaviorRegistry(behaviors), scenarios, None)

    assert result.resolved_count == 0
    assert result.total_count == len(ids)
    assert result.coverage_pct == 0.0
    assert {failure.scenario.behavior_id for failure in result.instrumentation_gaps} == set(ids)
    assert {behavior.behavior_id for behavior in result.unresolved_behaviors} == set(ids)


@given(st.lists(_ID, min_size=1, max_size=12, unique=True))
def test_symbol_less_behaviors_are_informational_only(ids: list[str]) -> None:
    behaviors = tuple(_behavior(behavior_id, None) for behavior_id in ids)
    scenarios = tuple(
        _scenario(behavior_id, line=index + 1) for index, behavior_id in enumerate(ids)
    )

    result = validate_attribution(BehaviorRegistry(behaviors), scenarios, None)

    assert result.is_complete
    assert result.total_count == 0
    assert result.resolved_count == 0
    assert result.coverage_pct == 0.0
    assert {behavior.behavior_id for behavior in result.informational_symbol_less} == set(ids)
    assert result.mis_attributed == ()
    assert result.unresolved_behaviors == ()
    assert result.instrumentation_gaps == ()


@given(
    rows=st.lists(
        st.tuples(_ID, _CLAIM_STATUS),
        max_size=12,
        unique_by=lambda row: row[0],
    ),
    aggregate_symbols=st.lists(st.text(min_size=1, max_size=20), max_size=8),
)
def test_validate_attribution_classifies_generated_claims(
    rows: list[tuple[str, str]], aggregate_symbols: list[str]
) -> None:
    behaviors = tuple(_behavior(behavior_id, f"pkg:{behavior_id}") for behavior_id, _ in rows)
    scenarios = tuple(
        _scenario(behavior_id, line=index + 1) for index, (behavior_id, _status) in enumerate(rows)
    )
    status_by_id = dict(rows)
    evidence = AttributionEvidence(
        tuple(
            ScenarioReach(
                scenario.feature_path,
                scenario.scenario_line,
                frozenset(
                    {f"pkg:{scenario.behavior_id}"}
                    if status_by_id[scenario.behavior_id] == "match"
                    else {f"other:{scenario.behavior_id}"}
                ),
            )
            for scenario in scenarios
            if status_by_id[scenario.behavior_id] != "gap"
        ),
        created_at=1.0,
    )

    result = validate_attribution(
        BehaviorRegistry(behaviors),
        scenarios,
        evidence,
        aggregate_reached_symbols=tuple(aggregate_symbols),
    )

    expected_matched = {behavior_id for behavior_id, status in rows if status == "match"}
    expected_missed = {behavior_id for behavior_id, status in rows if status == "miss"}
    expected_gaps = {behavior_id for behavior_id, status in rows if status == "gap"}
    assert result.resolved_count == len(expected_matched)
    assert result.total_count == len(rows)
    assert result.coverage_pct == (len(expected_matched) / len(rows) if rows else 0.0)
    assert {f.scenario.behavior_id for f in result.mis_attributed} == expected_missed
    assert {f.scenario.behavior_id for f in result.instrumentation_gaps} == expected_gaps
    assert {b.behavior_id for b in result.unresolved_behaviors} == (
        expected_missed | expected_gaps
    )
    assert result.aggregate_reached_symbols == tuple(sorted(set(aggregate_symbols)))


@given(
    rows=st.lists(
        st.tuples(_ID, _CLAIM_STATUS),
        max_size=12,
        unique_by=lambda row: row[0],
    )
)
def test_classify_claims_matches_generated_claim_model(rows: list[tuple[str, str]]) -> None:
    behaviors_by_id = {
        behavior_id: _behavior(behavior_id, f"pkg:{behavior_id}") for behavior_id, _ in rows
    }
    scenarios = tuple(
        _scenario(behavior_id, line=index + 1) for index, (behavior_id, _status) in enumerate(rows)
    )
    status_by_id = dict(rows)
    evidence = AttributionEvidence(
        tuple(
            ScenarioReach(
                scenario.feature_path,
                scenario.scenario_line,
                frozenset(
                    {f"pkg:{scenario.behavior_id}"}
                    if status_by_id[scenario.behavior_id] == "match"
                    else {f"other:{scenario.behavior_id}"}
                ),
            )
            for scenario in scenarios
            if status_by_id[scenario.behavior_id] != "gap"
        ),
        created_at=1.0,
    )

    mis_attributed, gaps, claimed_ids, attributed_ids = _classify_claims(
        behaviors_by_id, scenarios, evidence
    )

    assert claimed_ids == {behavior_id for behavior_id, _status in rows}
    assert attributed_ids == {behavior_id for behavior_id, status in rows if status == "match"}
    assert {failure.scenario.behavior_id for failure in mis_attributed} == {
        behavior_id for behavior_id, status in rows if status == "miss"
    }
    assert {failure.scenario.behavior_id for failure in gaps} == {
        behavior_id for behavior_id, status in rows if status == "gap"
    }


@given(
    behavior_rows=st.lists(
        st.tuples(_ID, st.booleans()),
        max_size=12,
        unique_by=lambda row: row[0],
    ),
    scenario_ids=st.lists(_ID, max_size=12, unique=True),
)
def test_classify_claims_ignores_unknown_and_symbol_less_behaviors(
    behavior_rows: list[tuple[str, bool]],
    scenario_ids: list[str],
) -> None:
    behaviors_by_id = {
        behavior_id: _behavior(behavior_id, f"pkg:{behavior_id}" if has_symbol else None)
        for behavior_id, has_symbol in behavior_rows
    }
    scenarios = tuple(
        _scenario(behavior_id, line=index + 1) for index, behavior_id in enumerate(scenario_ids)
    )

    mis_attributed, gaps, claimed_ids, attributed_ids = _classify_claims(
        behaviors_by_id, scenarios, None
    )

    expected_claimed = {
        behavior_id
        for behavior_id in scenario_ids
        if behavior_id in behaviors_by_id
        and behaviors_by_id[behavior_id].public_symbol is not None
    }
    assert mis_attributed == []
    assert claimed_ids == expected_claimed
    assert attributed_ids == set()
    assert {failure.scenario.behavior_id for failure in gaps} == expected_claimed


@given(
    live_ids=st.lists(_ID, max_size=12, unique=True),
    claimed_ids=st.lists(_ID, max_size=12, unique=True),
)
def test_validate_attribution_only_counts_claimed_symbol_bearing_behaviors(
    live_ids: list[str], claimed_ids: list[str]
) -> None:
    behaviors = tuple(_behavior(behavior_id, f"pkg:{behavior_id}") for behavior_id in live_ids)
    scenarios = tuple(
        _scenario(behavior_id, line=index + 1) for index, behavior_id in enumerate(claimed_ids)
    )

    result = validate_attribution(BehaviorRegistry(behaviors), scenarios, None)

    expected_claimed = set(live_ids) & set(claimed_ids)
    assert result.total_count == len(expected_claimed)
    assert result.resolved_count == 0
    assert {failure.scenario.behavior_id for failure in result.instrumentation_gaps} == (
        expected_claimed
    )
    assert {behavior.behavior_id for behavior in result.unresolved_behaviors} == expected_claimed


@given(
    evidence_failure=st.one_of(st.none(), st.text(min_size=1, max_size=30)),
    include_miss=st.booleans(),
    include_unresolved=st.booleans(),
    include_gap=st.booleans(),
    include_aggregate=st.booleans(),
    include_informational=st.booleans(),
)
def test_format_attribution_failure_sections_follow_result_contents(
    evidence_failure: str | None,
    include_miss: bool,
    include_unresolved: bool,
    include_gap: bool,
    include_aggregate: bool,
    include_informational: bool,
) -> None:
    scenario = _scenario("behavior")
    result = AttributionResult(
        mis_attributed=(
            (AttributionClaimFailure(scenario, "pkg:behavior"),) if include_miss else ()
        ),
        unresolved_behaviors=(
            (_behavior("unresolved", "pkg:unresolved"),) if include_unresolved else ()
        ),
        instrumentation_gaps=(
            (AttributionClaimFailure(scenario, "pkg:behavior"),) if include_gap else ()
        ),
        informational_symbol_less=(
            (_behavior("informational", None),) if include_informational else ()
        ),
        aggregate_reached_symbols=("pkg:diagnostic",) if include_aggregate else (),
        evidence_failure=evidence_failure,
    )

    message = format_attribution_failure(result)

    assert ("evidence failure:" in message) is bool(evidence_failure)
    assert ("mis-attributed:" in message) is include_miss
    assert ("unresolved behavior symbols:" in message) is include_unresolved
    assert ("instrumentation gaps:" in message) is include_gap
    assert ("aggregate trace fallback:" in message) is include_aggregate
    assert ("informational symbol-less behaviors:" in message) is include_informational


@given(
    ids=st.lists(_ID, max_size=8, unique=True),
    evidence_failure=st.one_of(
        st.none(),
        st.text(
            alphabet=st.characters(blacklist_characters="\r\n"),
            min_size=1,
            max_size=30,
        ),
    ),
    include_aggregate=st.booleans(),
)
def test_format_attribution_failure_line_count_matches_sections(
    ids: list[str],
    evidence_failure: str | None,
    include_aggregate: bool,
) -> None:
    failures = tuple(
        AttributionClaimFailure(_scenario(behavior_id, line=index + 1), f"pkg:{behavior_id}")
        for index, behavior_id in enumerate(ids)
    )
    symbol_behaviors = tuple(_behavior(behavior_id, f"pkg:{behavior_id}") for behavior_id in ids)
    informational = tuple(_behavior(behavior_id, None) for behavior_id in ids)
    result = AttributionResult(
        mis_attributed=failures,
        unresolved_behaviors=symbol_behaviors,
        instrumentation_gaps=failures,
        informational_symbol_less=informational,
        aggregate_reached_symbols=tuple(f"pkg:{behavior_id}" for behavior_id in ids)
        if include_aggregate
        else (),
        evidence_failure=evidence_failure,
    )

    line_count = len(format_attribution_failure(result).split("\n"))
    expected = 1
    expected += 1 if evidence_failure else 0
    expected += len(failures) + 1 if failures else 0
    expected += len(symbol_behaviors) + 1 if symbol_behaviors else 0
    expected += len(failures) + 1 if failures else 0
    expected += 1 if include_aggregate and ids else 0
    expected += len(informational) + 1 if informational else 0

    assert line_count == expected


@given(ids=st.lists(_ID, max_size=8, unique=True))
def test_attribution_formatter_helpers_emit_one_detail_per_item(ids: list[str]) -> None:
    failures = tuple(
        AttributionClaimFailure(_scenario(behavior_id, line=index + 1), f"pkg:{behavior_id}")
        for index, behavior_id in enumerate(ids)
    )
    behaviors = tuple(_behavior(behavior_id, f"pkg:{behavior_id}") for behavior_id in ids)
    informational = tuple(_behavior(behavior_id, None) for behavior_id in ids)

    mis_attributed = list(_format_mis_attributed(failures))
    unresolved = list(_format_unresolved(behaviors))
    gaps = list(_format_gaps(failures))
    info = list(_format_informational(informational))

    assert mis_attributed[0] == "  mis-attributed:"
    assert unresolved[0] == "  unresolved behavior symbols:"
    assert gaps[0] == "  instrumentation gaps:"
    assert info[0] == "  informational symbol-less behaviors:"
    assert len(mis_attributed) == len(ids) + 1
    assert len(unresolved) == len(ids) + 1
    assert len(gaps) == len(ids) + 1
    assert len(info) == len(ids) + 1
    for behavior_id in ids:
        assert behavior_id in "\n".join(mis_attributed)
        assert behavior_id in "\n".join(unresolved)
        assert behavior_id in "\n".join(gaps)
        assert behavior_id in "\n".join(info)


@given(behavior_id=_ID)
def test_attribution_formatter_helpers_name_their_failure_modes(behavior_id: str) -> None:
    scenario = _scenario(behavior_id)
    failure = AttributionClaimFailure(scenario, f"pkg:{behavior_id}")
    behavior = _behavior(behavior_id, f"pkg:{behavior_id}")
    informational = _behavior(behavior_id, None)

    assert "did not reach" in "\n".join(_format_mis_attributed((failure,)))
    assert "no claiming scenario reached it" in "\n".join(_format_unresolved((behavior,)))
    assert "no per-scenario evidence" in "\n".join(_format_gaps((failure,)))
    assert informational.summary in "\n".join(_format_informational((informational,)))


@given(
    feature_path=st.text(min_size=1, max_size=50),
    scenario_line=st.integers(min_value=1, max_value=1_000_000),
    symbols=st.lists(st.one_of(st.text(max_size=30), st.integers()), max_size=20),
)
def test_parse_reach_accepts_valid_positive_line_records(
    feature_path: str,
    scenario_line: int,
    symbols: list[object],
) -> None:
    parsed = _parse_reach({
        "feature_path": feature_path,
        "scenario_line": scenario_line,
        "reached_symbols": symbols,
    })

    assert parsed == ScenarioReach(
        Path(feature_path),
        scenario_line,
        frozenset(symbol for symbol in symbols if isinstance(symbol, str)),
    )


@given(st.integers(max_value=0))
def test_parse_reach_rejects_non_positive_scenario_lines(scenario_line: int) -> None:
    assert (
        _parse_reach({
            "feature_path": "features/example.feature",
            "scenario_line": scenario_line,
            "reached_symbols": [],
        })
        is None
    )


@given(
    st.one_of(
        st.none(),
        st.text(),
        st.lists(st.integers()),
        st.dictionaries(st.text(), st.text()),
    )
)
def test_parse_reach_never_raises_for_malformed_rows(raw: object) -> None:
    parsed = _parse_reach(raw)

    assert parsed is None or isinstance(parsed, ScenarioReach)


@given(st.floats(allow_nan=False, allow_infinity=False))
def test_load_evidence_accepts_finite_created_at(created_at: float) -> None:
    with TemporaryDirectory() as raw_root:
        path = Path(raw_root) / "behavior-attribution.json"
        path.write_text(
            json.dumps({"created_at": created_at, "scenarios": []}),
            encoding="utf-8",
        )

        evidence = load_evidence(path)

    assert evidence is not None
    assert math.isclose(evidence.created_at, created_at)


@given(st.one_of(st.booleans(), st.sampled_from([math.inf, -math.inf, math.nan])))
def test_load_evidence_rejects_boolean_and_nonfinite_created_at(created_at: object) -> None:
    with TemporaryDirectory() as raw_root:
        path = Path(raw_root) / "behavior-attribution.json"
        path.write_text(
            json.dumps({"created_at": created_at, "scenarios": []}),
            encoding="utf-8",
        )

        assert load_evidence(path) is None
