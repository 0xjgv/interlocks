"""Property tests for progressive baseline floor invariants."""

from __future__ import annotations

from pathlib import Path
from typing import Any, NoReturn

from hypothesis import given
from hypothesis import strategies as st

from interlocks.baseline import (
    METRICS,
    BaselineFloor,
    _pick_stricter,
    is_strictly_better,
    merge_higher,
)
from interlocks.run_summary import RunSummary
from interlocks.tasks import baseline_cmd as baseline_mod
from interlocks.tasks.baseline_cmd import (
    _baseline_error_payload,
    _baseline_usage,
    _floor_show_payload,
    _fmt,
    _metric_regression,
)

_VALUE = st.one_of(st.none(), st.floats(min_value=0, max_value=1000, allow_nan=False))
_FINITE = st.floats(min_value=0, max_value=1000, allow_nan=False, allow_infinity=False)


class _PayloadConfig:
    project_root = Path()

    @staticmethod
    def relpath(path: Path) -> str:
        return str(path)


@st.composite
def floors(draw: Any) -> BaselineFloor:
    return BaselineFloor(
        coverage_min=draw(_VALUE),
        mutation_min_score=draw(_VALUE),
        crap_max=draw(_VALUE),
        attribution_min_coverage=draw(_VALUE),
        lint_violations_max=draw(_VALUE),
        updated_at=draw(st.one_of(st.none(), st.just("2026-01-01T00:00:00Z"))),
        advanced_from_sha=draw(st.one_of(st.none(), st.text(min_size=1, max_size=12))),
    )


@given(floors(), floors())
def test_merge_higher_never_weakens_recorded_floors(
    left: BaselineFloor, right: BaselineFloor
) -> None:
    merged = merge_higher(left, right)

    for field, higher_is_stricter in METRICS:
        left_value = getattr(left, field)
        right_value = getattr(right, field)
        merged_value = getattr(merged, field)
        candidates = [value for value in (left_value, right_value) if value is not None]
        if not candidates:
            assert merged_value is None
        elif higher_is_stricter:
            assert merged_value == max(candidates)
        else:
            assert merged_value == min(candidates)


@given(floors())
def test_floor_is_not_strictly_better_than_itself(floor: BaselineFloor) -> None:
    assert is_strictly_better(floor, floor) is False


@given(floors(), floors())
def test_merged_floor_cannot_regress_against_inputs(
    left: BaselineFloor, right: BaselineFloor
) -> None:
    merged = merge_higher(left, right)

    for base in (left, right):
        assert is_strictly_better(merged, base) or _same_metric_values(merged, base)


def _same_metric_values(left: BaselineFloor, right: BaselineFloor) -> bool:
    return all(getattr(left, field) == getattr(right, field) for field, _ in METRICS)


@given(message=st.text(min_size=1, max_size=120))
def test_baseline_error_payload_lists_action_domain(message: str) -> None:
    payload = _baseline_error_payload(message)

    assert payload["command"] == "baseline"
    assert payload["error"] == message
    assert payload["usage"] == _baseline_usage()
    assert payload["expected_actions"] == ["show", "init", "advance", "check"]
    assert "show|init|advance|check" in str(payload["usage"])


@given(summary_present=st.booleans(), json_mode=st.booleans())
def test_require_summary_returns_loaded_summary_or_exits(
    summary_present: bool, json_mode: bool
) -> None:
    summary = RunSummary(coverage_pct=75.0)
    printed: list[object] = []

    def fake_load_summary(_cfg: object) -> RunSummary | None:
        return summary if summary_present else None

    def fake_print_json(payload: object) -> None:
        printed.append(payload)

    def fake_fail_skip(_message: str) -> NoReturn:
        raise SystemExit(1)

    old_load_summary = baseline_mod.load_summary
    old_print_json = baseline_mod.ui.print_json
    old_fail_skip = baseline_mod.fail_skip
    baseline_mod.load_summary = fake_load_summary  # type: ignore[assignment]
    baseline_mod.ui.print_json = fake_print_json  # type: ignore[assignment]
    baseline_mod.fail_skip = fake_fail_skip  # type: ignore[assignment]
    try:
        _assert_require_summary_behavior(summary_present, json_mode, summary, printed)
    finally:
        baseline_mod.load_summary = old_load_summary  # type: ignore[assignment]
        baseline_mod.ui.print_json = old_print_json  # type: ignore[assignment]
        baseline_mod.fail_skip = old_fail_skip  # type: ignore[assignment]


def _assert_require_summary_behavior(
    summary_present: bool,
    json_mode: bool,
    summary: RunSummary,
    printed: list[object],
) -> None:
    if summary_present:
        result = baseline_mod._require_summary(
            _PayloadConfig(),  # type: ignore[arg-type]
            json_mode=json_mode,
        )
        assert result is summary
        assert printed == []
        return

    try:
        baseline_mod._require_summary(
            _PayloadConfig(),  # type: ignore[arg-type]
            json_mode=json_mode,
        )
    except SystemExit as exc:
        assert exc.code == 1
    else:  # pragma: no cover - guarded by the assertion above
        raise AssertionError("_require_summary should exit when no summary exists")
    assert bool(printed) is json_mode


@given(
    a=st.one_of(st.none(), _FINITE),
    b=st.one_of(st.none(), _FINITE),
    higher_better=st.booleans(),
)
def test_pick_stricter_chooses_present_stricter_value(
    a: float | None,
    b: float | None,
    higher_better: bool,
) -> None:
    picked = _pick_stricter(a, b, higher_better)
    present = [value for value in (a, b) if value is not None]

    if not present:
        assert picked is None
    elif higher_better:
        assert picked == max(present)
    else:
        assert picked == min(present)


@given(
    a=st.one_of(st.none(), _FINITE),
    b=st.one_of(st.none(), _FINITE),
    higher_better=st.booleans(),
)
def test_pick_stricter_is_order_independent(
    a: float | None,
    b: float | None,
    higher_better: bool,
) -> None:
    assert _pick_stricter(a, b, higher_better) == _pick_stricter(b, a, higher_better)


@given(
    field=st.sampled_from([field for field, _higher_better in METRICS]),
    measured=st.one_of(st.none(), _FINITE),
    current_floor=st.one_of(st.none(), _FINITE),
    higher_better=st.booleans(),
)
def test_metric_regression_only_reports_strict_floor_misses(
    field: str,
    measured: float | None,
    current_floor: float | None,
    higher_better: bool,
) -> None:
    regression = _metric_regression(
        field,
        measured=measured,
        current_floor=current_floor,
        higher_better=higher_better,
    )

    if measured is None or current_floor is None:
        assert regression is None
    elif higher_better:
        assert (regression is not None) is (measured < current_floor)
    else:
        assert (regression is not None) is (measured > current_floor)


@given(_FINITE)
def test_baseline_value_formatting_rounds_to_at_most_two_decimals(value: float) -> None:
    formatted = _fmt(value)

    assert formatted == str(int(round(value, 2))) or "." in formatted
    if "." in formatted:
        assert len(formatted.rsplit(".", 1)[1]) <= 2


@given(floors())
def test_floor_show_payload_marks_empty_floor_and_next_action(floor: BaselineFloor) -> None:
    payload = _floor_show_payload(_PayloadConfig(), floor)  # type: ignore[arg-type]

    assert payload["baseline_present"] is (not floor.is_empty)
    assert ("next_action" in payload) is floor.is_empty
    if floor.is_empty:
        assert "baseline init" in str(payload["next_action"])
