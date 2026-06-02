"""Property tests for lintfix replay statistics."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from hypothesis import given
from hypothesis import strategies as st

from interlocks.lintfix.stats import (
    CandidateSample,
    RuleStats,
    _aggregate_one,
    _dominates,
    _pareto_frontier,
    _promotion_decision,
    _promotion_eligible,
    _recommend,
    aggregate,
    quantile,
)

if TYPE_CHECKING:
    from interlocks.lintfix.rules import Mode

_MODES = st.sampled_from(("auto", "escrow", "advisory", "skip"))
_LINES = st.integers(min_value=0, max_value=10_000)


def _sample(
    *,
    rule: str,
    classification: str,
    total: int,
    outside: int,
    unsafe: bool,
    reverted: bool,
    commit: str,
) -> CandidateSample:
    return CandidateSample(
        rule=rule,
        mutation_class="other",
        classification=cast("Mode", classification),
        changed_lines_total=total,
        changed_lines_outside_diff=outside,
        risk=0,
        unsafe=unsafe,
        commit=commit,
        reverted_in="revert" if reverted else None,
    )


def _stats(
    *,
    rule: str = "F401",
    current_mode: str = "escrow",
    prs_with_candidate: int = 3,
    prs_helped: int = 3,
    p95_outside: float = 0.0,
    unsafe_seen: bool = False,
    revert_signal: int = 0,
) -> RuleStats:
    return RuleStats(
        rule=rule,
        mutation_class="other",
        current_mode=cast("Mode", current_mode),
        prs_with_candidate=prs_with_candidate,
        prs_helped=prs_helped,
        median_changed_lines=0.0,
        p95_changed_lines=0.0,
        median_outside_diff_lines=0.0,
        p95_outside_diff_lines=p95_outside,
        unsafe_seen=unsafe_seen,
        revert_signal=revert_signal,
        on_pareto_frontier=False,
        recommended_mode=current_mode,
        rationale="",
    )


def _linear_quantile(values: list[int], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(values)
    pos = q * (len(ordered) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac


@given(values=st.lists(_LINES, max_size=30), q=st.floats(min_value=0, max_value=1))
def test_quantile_matches_linear_reference(values: list[int], q: float) -> None:
    assert quantile(values, q) == _linear_quantile(values, q)


@given(
    rows=st.lists(
        st.tuples(_MODES, _LINES, _LINES, st.booleans(), st.booleans()),
        min_size=1,
        max_size=30,
    )
)
def test_aggregate_preserves_generated_rule_counts(
    rows: list[tuple[str, int, int, bool, bool]],
) -> None:
    samples = [
        _sample(
            rule="F401",
            classification=classification,
            total=total,
            outside=outside,
            unsafe=unsafe,
            reverted=reverted,
            commit=f"c{index}",
        )
        for index, (classification, total, outside, unsafe, reverted) in enumerate(rows)
    ]

    [stats] = aggregate(samples)

    totals = [row[1] for row in rows]
    outside_lines = [row[2] for row in rows]
    assert stats.rule == "F401"
    assert stats.prs_with_candidate == len(rows)
    assert stats.prs_helped == sum(
        1 for classification, *_rest in rows if classification != "skip"
    )
    assert stats.median_changed_lines == quantile(totals, 0.5)
    assert stats.p95_changed_lines == quantile(totals, 0.95)
    assert stats.median_outside_diff_lines == quantile(outside_lines, 0.5)
    assert stats.p95_outside_diff_lines == quantile(outside_lines, 0.95)
    assert stats.unsafe_seen is any(row[3] for row in rows)
    assert stats.revert_signal == sum(1 for row in rows if row[4])


@given(
    rows=st.lists(
        st.tuples(_MODES, _LINES, _LINES, st.booleans(), st.booleans()),
        min_size=1,
        max_size=30,
    )
)
def test_aggregate_one_matches_generated_observation_model(
    rows: list[tuple[str, int, int, bool, bool]],
) -> None:
    samples = [
        _sample(
            rule="F401",
            classification=classification,
            total=total,
            outside=outside,
            unsafe=unsafe,
            reverted=reverted,
            commit=f"c{index}",
        )
        for index, (classification, total, outside, unsafe, reverted) in enumerate(rows)
    ]

    stats = _aggregate_one("F401", samples)

    assert stats.prs_with_candidate == len(rows)
    assert stats.prs_helped == sum(
        1 for classification, *_rest in rows if classification != "skip"
    )
    assert stats.unsafe_seen is any(row[3] for row in rows)
    assert stats.revert_signal == sum(1 for row in rows if row[4])


@given(rule=st.sampled_from(["F401", "I001", "C4", "UNKNOWN999"]))
def test_aggregate_one_preserves_policy_identity_with_no_observations(rule: str) -> None:
    stats = _aggregate_one(rule, ())

    assert stats.rule == rule
    assert stats.prs_with_candidate == 0
    assert stats.prs_helped == 0
    assert stats.median_changed_lines == 0
    assert stats.p95_outside_diff_lines == 0
    assert stats.recommended_mode == stats.current_mode


@given(helped=st.integers(min_value=0, max_value=20), p95=st.floats(min_value=0, max_value=50))
def test_pareto_frontier_drops_strictly_dominated_rules(helped: int, p95: float) -> None:
    dominant = _stats(rule="F401", prs_helped=helped + 1, p95_outside=p95)
    dominated = _stats(rule="I001", prs_helped=helped, p95_outside=p95 + 1)

    assert _pareto_frontier((dominated, dominant)) == frozenset({"F401"})


@given(
    rows=st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=20),
            st.floats(min_value=0, max_value=50),
            st.booleans(),
        ),
        max_size=20,
    )
)
def test_pareto_frontier_contains_exactly_non_dominated_rules(
    rows: list[tuple[int, float, bool]],
) -> None:
    stats = tuple(
        _stats(
            rule=f"R{index}",
            prs_helped=helped,
            p95_outside=p95,
            unsafe_seen=unsafe,
        )
        for index, (helped, p95, unsafe) in enumerate(rows)
    )

    frontier = _pareto_frontier(stats)

    assert frontier == frozenset(
        candidate.rule
        for candidate in stats
        if not any(_dominates(other, candidate) for other in stats if other is not candidate)
    )


@given(
    helped_a=st.integers(min_value=0, max_value=20),
    helped_b=st.integers(min_value=0, max_value=20),
    p95_a=st.floats(min_value=0, max_value=50),
    p95_b=st.floats(min_value=0, max_value=50),
    unsafe_a=st.booleans(),
    unsafe_b=st.booleans(),
)
def test_dominates_matches_strict_pareto_rule(
    helped_a: int,
    helped_b: int,
    p95_a: float,
    p95_b: float,
    unsafe_a: bool,
    unsafe_b: bool,
) -> None:
    a = _stats(rule="A001", prs_helped=helped_a, p95_outside=p95_a, unsafe_seen=unsafe_a)
    b = _stats(rule="B001", prs_helped=helped_b, p95_outside=p95_b, unsafe_seen=unsafe_b)

    expected = (
        not (unsafe_a and not unsafe_b)
        and helped_a >= helped_b
        and p95_a <= p95_b
        and (helped_a > helped_b or p95_a < p95_b)
    )
    assert _dominates(a, b) is expected


@given(unsafe=st.booleans(), observations=st.integers(min_value=0, max_value=12))
def test_recommend_prioritizes_unsafe_and_observation_floor(
    unsafe: bool,
    observations: int,
) -> None:
    stats = _stats(rule="F401", prs_with_candidate=observations, unsafe_seen=unsafe)

    mode, rationale = _recommend(stats, on_frontier=True)

    if unsafe:
        assert mode == "skip"
        assert "unsafe" in rationale
    elif observations < 3:
        assert mode == "needs_data"
        assert "floor=3" in rationale
    else:
        assert mode in {"auto", "escrow"}


@given(revert_signal=st.integers(min_value=1, max_value=20))
def test_recommend_demotes_reverted_auto_rules(revert_signal: int) -> None:
    stats = _stats(
        rule="F401",
        current_mode="auto",
        prs_with_candidate=3,
        unsafe_seen=False,
        revert_signal=revert_signal,
    )

    mode, rationale = _recommend(stats, on_frontier=True)

    assert mode == "escrow"
    assert "reverted" in rationale


@given(exact=st.booleans(), on_frontier=st.booleans(), p95=st.floats(min_value=0, max_value=10))
def test_promotion_decision_requires_frontier_low_churn_and_escrow_mode(
    exact: bool,
    on_frontier: bool,
    p95: float,
) -> None:
    stats = _stats(rule="F401" if exact else "X999", current_mode="escrow", p95_outside=p95)

    decision = _promotion_decision(stats, exact=exact, on_frontier=on_frontier)

    if on_frontier and p95 <= 5:
        assert decision is not None
        assert decision[0] == ("auto" if exact else "escrow")
    else:
        assert decision is None


@given(current_mode=st.sampled_from(["auto", "advisory", "skip"]), exact=st.booleans())
def test_promotion_decision_only_promotes_from_escrow_mode(
    current_mode: str,
    exact: bool,
) -> None:
    stats = _stats(
        rule="F401" if exact else "X999",
        current_mode=current_mode,
        p95_outside=0.0,
        revert_signal=0,
    )

    assert _promotion_decision(stats, exact=exact, on_frontier=True) is None


@given(
    on_frontier=st.booleans(),
    p95=st.floats(min_value=0, max_value=10),
    current_mode=_MODES,
    revert_signal=st.integers(min_value=0, max_value=3),
)
def test_promotion_eligible_requires_frontier_low_churn_no_reverts_and_escrow(
    on_frontier: bool,
    p95: float,
    current_mode: str,
    revert_signal: int,
) -> None:
    stats = _stats(
        current_mode=current_mode,
        p95_outside=p95,
        revert_signal=revert_signal,
    )

    eligible = _promotion_eligible(stats, on_frontier=on_frontier)

    assert eligible is (
        on_frontier and p95 <= 5 and revert_signal == 0 and current_mode == "escrow"
    )
