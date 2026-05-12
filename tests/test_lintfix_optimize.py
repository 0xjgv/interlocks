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
