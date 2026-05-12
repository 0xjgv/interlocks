"""Unit tests for ``interlocks.lintfix.stats`` — aggregation, Pareto, recommendations.

Each test feeds synthetic :class:`CandidateSample` records to ``aggregate``
and checks one specific dimension of the output (a percentile, a frontier
decision, a recommendation transition). No real git/ruff is involved.
"""

from __future__ import annotations

from interlocks.lintfix.stats import (
    CandidateSample,
    aggregate,
    quantile,
)


def _sample(
    *,
    rule: str,
    classification: str = "auto",
    outside: int = 0,
    total: int = 1,
    unsafe: bool = False,
    commit: str = "deadbeef",
    reverted_in: str | None = None,
    mutation_class: str = "import_sort",
) -> CandidateSample:
    return CandidateSample(
        rule=rule,
        mutation_class=mutation_class,
        classification=classification,  # type: ignore[arg-type]
        changed_lines_total=total,
        changed_lines_outside_diff=outside,
        risk=0,
        unsafe=unsafe,
        commit=commit,
        reverted_in=reverted_in,
    )


def test_quantile_handles_single_and_empty_inputs() -> None:
    assert quantile([], 0.5) == 0.0
    assert quantile([7], 0.95) == 7.0


def test_quantile_linear_interpolation_matches_classic_definition() -> None:
    # values=[1,2,3,4], q=0.5 -> pos=1.5 -> 2 + 0.5*(3-2) = 2.5
    assert quantile([1, 2, 3, 4], 0.5) == 2.5
    # q=0.95 over 21 values: pos=19.0 -> exact value 20
    assert quantile(list(range(1, 22)), 0.95) == 20.0


def test_aggregate_counts_prs_helped_excludes_skip() -> None:
    samples = [
        _sample(rule="I001", classification="auto", commit="c1"),
        _sample(rule="I001", classification="skip", commit="c2"),
        _sample(rule="I001", classification="escrow", commit="c3"),
    ]
    [stats] = aggregate(samples)
    assert stats.prs_with_candidate == 3
    assert stats.prs_helped == 2


def test_aggregate_promotes_exact_catalog_rule_on_low_churn() -> None:
    samples = [
        _sample(rule="F401", classification="escrow", outside=1, commit=f"c{i}") for i in range(5)
    ]
    [stats] = aggregate(samples)
    assert stats.on_pareto_frontier is True
    # F401's catalog default is escrow; low p95-outside should promote it.
    assert stats.recommended_mode == "auto"


def test_aggregate_refuses_to_promote_prefix_fallback_rule() -> None:
    """SIM117 reaches the catalog via the SIM prefix → must not auto-promote."""
    samples = [
        _sample(
            rule="SIM117",
            classification="escrow",
            outside=1,
            commit=f"c{i}",
            mutation_class="control_flow_or_style",
        )
        for i in range(15)
    ]
    [stats] = aggregate(samples)
    assert stats.current_mode == "advisory"
    assert stats.recommended_mode != "auto"


def test_aggregate_marks_needs_data_below_observation_floor() -> None:
    samples = [_sample(rule="W292", classification="auto", commit="c1")]
    [stats] = aggregate(samples)
    assert stats.recommended_mode == "needs_data"


def test_aggregate_demotes_auto_rule_with_high_outside_diff_churn() -> None:
    samples = [_sample(rule="I001", outside=50, commit=f"c{i}") for i in range(5)]
    [stats] = aggregate(samples)
    assert stats.current_mode == "auto"
    assert stats.recommended_mode == "escrow"


def test_aggregate_demotes_auto_rule_on_revert_signal() -> None:
    samples = [
        _sample(rule="I001", outside=1, commit=f"c{i}", reverted_in="r1" if i < 2 else None)
        for i in range(5)
    ]
    [stats] = aggregate(samples)
    assert stats.revert_signal == 2
    assert stats.recommended_mode == "escrow"


def test_aggregate_marks_unsafe_rule_as_skip() -> None:
    samples = [_sample(rule="F401", unsafe=True, commit=f"c{i}") for i in range(5)]
    [stats] = aggregate(samples)
    assert stats.unsafe_seen is True
    assert stats.recommended_mode == "skip"


def test_pareto_frontier_excludes_dominated_rules() -> None:
    # I001: 5 PRs helped, p95 outside-diff = 1 → dominates W292
    # W292: 3 PRs helped, p95 outside-diff = 4
    # Both should land on the frontier only if neither dominates the other.
    i_samples = [_sample(rule="I001", outside=1, commit=f"i{i}") for i in range(5)]
    w_samples = [_sample(rule="W292", outside=4, commit=f"w{i}") for i in range(3)]
    by_rule = {s.rule: s for s in aggregate([*i_samples, *w_samples])}
    assert by_rule["I001"].on_pareto_frontier is True
    assert by_rule["W292"].on_pareto_frontier is False


def test_pareto_frontier_unsafe_rule_cannot_dominate_safe_rule() -> None:
    unsafe = [_sample(rule="X001", outside=0, unsafe=True, commit=f"u{i}") for i in range(10)]
    safe = [_sample(rule="I001", outside=2, commit=f"s{i}") for i in range(5)]
    by_rule = {s.rule: s for s in aggregate([*unsafe, *safe])}
    # Even though X001 has more PRs helped and lower outside-diff, it must not
    # push I001 off the frontier.
    assert by_rule["I001"].on_pareto_frontier is True
