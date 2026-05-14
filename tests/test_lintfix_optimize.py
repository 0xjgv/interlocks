"""Unit tests for ``interlocks.lintfix.optimize``.

Covers the value function, the candidate-from-plan mapping, conflict
detection, and the Pareto-pruned DP — all on synthetic inputs so no ruff
or git is involved.
"""

from __future__ import annotations

from interlocks.lintfix import optimize
from interlocks.lintfix.budgets import UNBLOCK, Budget, CandidateCost
from interlocks.lintfix.classify import CandidateMetrics, Classification
from interlocks.lintfix.plan import PlannedCandidate
from interlocks.lintfix.stats import RuleStats


def _planned(
    rule: str,
    *,
    mode: str = "auto",
    files: tuple[str, ...] = ("a.py",),
    total: int = 4,
    inside: int = 4,
    outside: int = 0,
    risk: int = 2,
    diagnostic_count: int = 1,
    unsafe: bool = False,
) -> PlannedCandidate:
    metrics = CandidateMetrics(
        files_touched=files,
        changed_lines_total=total,
        changed_lines_inside_diff=inside,
        changed_lines_outside_diff=outside,
        comment_deletes=0,
        control_flow_edits=0,
    )
    cost = CandidateCost(
        files_touched=len(files),
        changed_lines_total=total,
        changed_lines_outside_diff=outside,
        risk=risk,
        unsafe=unsafe,
    )
    classification = Classification(
        rule=rule,
        mode=mode,  # type: ignore[arg-type]
        metrics=metrics,
        cost=cost,
        reason=None,
        patch_id=f"{rule}:{':'.join(files)}",
    )
    return PlannedCandidate(
        classification=classification,
        diff_text=f"--- patch for {rule}\n",
        unsafe=unsafe,
        diagnostic_count=diagnostic_count,
        mutation_class="import_sort",
    )


def _candidate(
    rule: str,
    *,
    value: int,
    outside: int = 0,
    lines: int = 1,
    files_count: int = 1,
    risk: int = 0,
    files: tuple[str, ...] | None = None,
    selectable: bool = True,
    policy_mode: str = "auto",
    unsafe: bool = False,
) -> optimize.Candidate:
    return optimize.Candidate(
        rule=rule,
        value=value,
        cost=optimize.CostVector(
            outside_diff=outside,
            changed_lines=lines,
            files=files_count,
            risk=risk,
        ),
        files=files if files is not None else (f"{rule.lower()}.py",),
        selectable=selectable,
        policy_mode=policy_mode,
        unsafe=unsafe,
    )


def _plan(selected: set[int], *, value: int, outside: int = 0) -> optimize._Plan:
    return optimize._Plan(
        selected=frozenset(selected),
        value=value,
        cost=optimize.CostVector(outside_diff=outside, changed_lines=0, files=0, risk=0),
        files=frozenset(),
    )


def _rule_stats(*, prs_helped: int, unsafe_seen: bool = False) -> RuleStats:
    return RuleStats(
        rule="I001",
        mutation_class="import_sort",
        current_mode="auto",
        prs_with_candidate=prs_helped,
        prs_helped=prs_helped,
        median_changed_lines=0.0,
        p95_changed_lines=0.0,
        median_outside_diff_lines=0.0,
        p95_outside_diff_lines=0.0,
        unsafe_seen=unsafe_seen,
        revert_signal=0,
        on_pareto_frontier=False,
        recommended_mode="auto",
        rationale="",
    )


# --- value_for -----------------------------------------------------------


def test_value_for_skip_candidate_is_zero() -> None:
    planned = _planned("I001", mode="skip", total=0, inside=0)
    assert optimize.value_for(planned) == 0


def test_value_for_advisory_applies_penalty() -> None:
    planned = _planned("SIM102", mode="advisory", diagnostic_count=1, inside=0, outside=0)
    # findings(8) + support(0) + noise(0) - penalty(2) = 6
    assert optimize.value_for(planned) == 6


def test_value_for_rewards_inside_diff_over_outside() -> None:
    inside_heavy = _planned("I001", diagnostic_count=1, inside=10, outside=2)
    outside_heavy = _planned("I001", diagnostic_count=1, inside=2, outside=10)
    assert optimize.value_for(inside_heavy) > optimize.value_for(outside_heavy)


# --- candidates_from_plan -------------------------------------------------


def test_candidates_from_plan_marks_auto_as_selectable() -> None:
    planned = (_planned("I001", mode="auto"),)
    [candidate] = optimize.candidates_from_plan(planned)
    assert candidate.selectable is True
    assert candidate.policy_mode == "auto"


def test_candidates_from_plan_marks_escrow_as_unselectable() -> None:
    planned = (_planned("F401", mode="escrow"),)
    [candidate] = optimize.candidates_from_plan(planned)
    assert candidate.selectable is False
    assert candidate.policy_mode == "escrow"


def test_candidates_from_plan_marks_unsafe_as_unselectable() -> None:
    planned = (_planned("T201", mode="auto", unsafe=True),)
    [candidate] = optimize.candidates_from_plan(planned)
    assert candidate.selectable is False
    assert candidate.unsafe is True


# --- conflict detection ---------------------------------------------------


def test_conflicts_when_files_overlap() -> None:
    a = _candidate("I001", value=10, files=("a.py", "b.py"))
    b = _candidate("W292", value=5, files=("b.py",))
    assert optimize.conflicts(a, b) is True


def test_no_conflict_when_files_disjoint() -> None:
    a = _candidate("I001", value=10, files=("a.py",))
    b = _candidate("W292", value=5, files=("b.py",))
    assert optimize.conflicts(a, b) is False


# --- DP optimization ------------------------------------------------------


def test_optimize_empty_candidates_returns_empty_selection() -> None:
    result = optimize.optimize((), UNBLOCK)
    assert result.selected == ()
    assert result.rejected == ()
    assert result.total_value == 0


def test_optimize_picks_single_fitting_candidate() -> None:
    candidates = (_candidate("I001", value=20, outside=1, risk=2),)
    result = optimize.optimize(candidates, UNBLOCK)
    assert [s.candidate.rule for s in result.selected] == ["I001"]
    assert result.total_value == 20


def test_optimize_rejects_candidate_exceeding_risk_budget() -> None:
    candidates = (_candidate("HIGH_RISK", value=100, outside=0, lines=1, files_count=1, risk=999),)
    result = optimize.optimize(candidates, UNBLOCK)
    assert result.selected == ()
    [rejected] = result.rejected
    assert "risk" in rejected.reason


def test_optimize_rejects_unsafe_candidate_in_unblock() -> None:
    candidates = (_candidate("T201", value=50, selectable=False, unsafe=True, policy_mode="auto"),)
    result = optimize.optimize(candidates, UNBLOCK)
    assert result.selected == ()
    [rejected] = result.rejected
    assert "unsafe" in rejected.reason


def test_optimize_rejects_escrow_candidate_with_policy_reason() -> None:
    candidates = (_candidate("F401", value=15, selectable=False, policy_mode="escrow"),)
    result = optimize.optimize(candidates, UNBLOCK)
    [rejected] = result.rejected
    assert "escrow" in rejected.reason


def test_optimize_resolves_conflict_by_taking_higher_value() -> None:
    """Two candidates touching the same file — only the higher-value one wins."""
    candidates = (
        _candidate("LO", value=5, files=("shared.py",)),
        _candidate("HI", value=20, files=("shared.py",)),
    )
    result = optimize.optimize(candidates, UNBLOCK)
    assert [s.candidate.rule for s in result.selected] == ["HI"]
    [rejected] = result.rejected
    assert rejected.candidate.rule == "LO"
    assert "HI" in rejected.reason  # blocker named in the reason


def test_optimize_picks_max_value_subset_under_budget() -> None:
    """Anti-greedy knapsack: greedy-by-value picks A alone, DP picks B+C."""
    tight = Budget(
        name="tight",
        max_files=10,
        max_changed_lines=100,
        max_outside_diff_lines=100,
        max_risk=6,  # binding constraint
    )
    # A alone fits (value 10, risk 5).
    # B+C together fit (value 14, risk 6) and beat A.
    # A+B or A+C both exceed risk 6.
    candidates = (
        _candidate("A", value=10, files=("a.py",), risk=5),
        _candidate("B", value=7, files=("b.py",), risk=3),
        _candidate("C", value=7, files=("c.py",), risk=3),
    )
    result = optimize.optimize(candidates, tight)
    chosen = {s.candidate.rule for s in result.selected}
    assert chosen == {"B", "C"}
    assert result.total_value == 14


def test_optimize_total_cost_matches_sum_of_selected() -> None:
    candidates = (
        _candidate("A", value=10, files=("a.py",), outside=1, lines=4, risk=2),
        _candidate("B", value=10, files=("b.py",), outside=2, lines=6, risk=3),
    )
    result = optimize.optimize(candidates, UNBLOCK)
    assert {s.candidate.rule for s in result.selected} == {"A", "B"}
    assert result.total_cost.outside_diff == 3
    assert result.total_cost.changed_lines == 10
    assert result.total_cost.files == 2
    assert result.total_cost.risk == 5


def test_optimize_explains_displaced_candidate() -> None:
    """A candidate that fits in isolation but is squeezed out by a higher-value
    pick on a different file should get a clear 'displaced' reason."""
    budget = Budget(
        name="cap-by-lines",
        max_files=10,
        max_changed_lines=10,  # binding
        max_outside_diff_lines=100,
        max_risk=100,
    )
    candidates = (
        _candidate("BIG", value=100, files=("a.py",), lines=10, risk=0),
        _candidate("SMALL", value=1, files=("b.py",), lines=5, risk=0),
    )
    result = optimize.optimize(candidates, budget)
    assert [s.candidate.rule for s in result.selected] == ["BIG"]
    [rejected] = result.rejected
    assert rejected.candidate.rule == "SMALL"
    # SMALL alone fits, but adding it to BIG bursts the lines budget.
    assert "changed-lines" in rejected.reason or "displaced" in rejected.reason


# --- CostVector ----------------------------------------------------------


def test_cost_vector_add_sums_all_dimensions() -> None:
    a = optimize.CostVector(outside_diff=1, changed_lines=2, files=3, risk=4)
    b = optimize.CostVector(outside_diff=10, changed_lines=20, files=30, risk=40)
    assert a + b == optimize.CostVector(outside_diff=11, changed_lines=22, files=33, risk=44)


# --- Pareto domination / pruning -----------------------------------------


def test_dominates_true_on_strict_improvement() -> None:
    # equal value, strictly cheaper in one dimension → a dominates b.
    a = _plan({0}, value=10, outside=0)
    b = _plan({1}, value=10, outside=5)
    assert optimize._dominates(a, b) is True


def test_dominates_false_for_same_selection() -> None:
    a = _plan({0}, value=10, outside=0)
    b = _plan({0}, value=5, outside=5)
    assert optimize._dominates(a, b) is False


def test_dominates_false_when_value_lower() -> None:
    a = _plan({0}, value=5)
    b = _plan({1}, value=10)
    assert optimize._dominates(a, b) is False


def test_dominates_false_when_not_cost_le_everywhere() -> None:
    # a wins on value but is more expensive on outside-diff → no domination.
    a = _plan({0}, value=20, outside=5)
    b = _plan({1}, value=10, outside=0)
    assert optimize._dominates(a, b) is False


def test_prune_dominated_drops_strictly_dominated_plan() -> None:
    strong = _plan({0}, value=10, outside=0)
    weak = _plan({1}, value=5, outside=5)
    assert optimize._prune_dominated([strong, weak]) == [strong]


def test_prune_dominated_keeps_pareto_incomparable_plans() -> None:
    # higher value but also higher cost → neither dominates the other.
    cheap = _plan({0}, value=5, outside=0)
    pricey = _plan({1}, value=20, outside=10)
    assert set(optimize._prune_dominated([cheap, pricey])) == {cheap, pricey}


# --- optimize tie-break --------------------------------------------------


def test_optimize_tie_break_prefers_lower_risk() -> None:
    """Equal-value, disjoint-file candidates that can't both fit the risk
    budget → the tie-break key picks the lower-risk one."""
    budget = Budget(
        name="risk-capped",
        max_files=10,
        max_changed_lines=100,
        max_outside_diff_lines=100,
        max_risk=5,  # fits either candidate alone, never both
    )
    candidates = (
        _candidate("RISKY", value=10, files=("a.py",), risk=5),
        _candidate("SAFE", value=10, files=("b.py",), risk=1),
    )
    result = optimize.optimize(candidates, budget)
    assert [s.candidate.rule for s in result.selected] == ["SAFE"]


# --- value_for with replay stats -----------------------------------------


def test_value_for_adds_replay_support_score() -> None:
    planned = _planned("I001", diagnostic_count=1, inside=0, outside=0)
    stats = _rule_stats(prs_helped=3)
    # findings(8) + support(5*3) + noise(0) - penalty(0) = 23
    assert optimize.value_for(planned, stats) == 23


def test_value_for_unsafe_seen_stats_contribute_zero_support() -> None:
    planned = _planned("I001", diagnostic_count=1, inside=0, outside=0)
    stats = _rule_stats(prs_helped=3, unsafe_seen=True)
    # unsafe_seen zeroes the support term → findings(8) only
    assert optimize.value_for(planned, stats) == 8


def test_candidates_from_plan_applies_stats_support_score() -> None:
    planned = (_planned("I001", diagnostic_count=1, inside=0, outside=0),)
    stats = {"I001": _rule_stats(prs_helped=2)}
    [candidate] = optimize.candidates_from_plan(planned, stats)
    # findings(8) + support(5*2) = 18
    assert candidate.value == 18


def test_value_for_floors_at_zero() -> None:
    # advisory penalty would drive value negative; the floor clamps to 0.
    planned = _planned("SIM102", mode="advisory", diagnostic_count=0, inside=0, outside=0)
    assert optimize.value_for(planned) == 0


# --- _budget_overflow reason branches ------------------------------------


def test_budget_overflow_reports_outside_diff() -> None:
    budget = Budget(
        name="b",
        max_files=100,
        max_changed_lines=1000,
        max_outside_diff_lines=5,  # binding
        max_risk=100,
    )
    candidate = _candidate("X", value=1, outside=10, lines=1, files_count=1)
    assert optimize._budget_overflow(candidate, optimize._Plan(), budget) == "outside-diff"


def test_budget_overflow_reports_files() -> None:
    budget = Budget(
        name="b",
        max_files=1,  # binding
        max_changed_lines=1000,
        max_outside_diff_lines=1000,
        max_risk=100,
    )
    candidate = _candidate("X", value=1, outside=0, lines=1, files_count=5)
    assert optimize._budget_overflow(candidate, optimize._Plan(), budget) == "files"
