"""Property tests for lintfix budget profiles."""

from __future__ import annotations

from math import floor

from hypothesis import given
from hypothesis import strategies as st

from interlocks.lintfix.budgets import (
    RENOVATION,
    UNBLOCK,
    Budget,
    CandidateCost,
    check_budget,
    dynamic,
    profile,
)

_COUNT = st.integers(min_value=0, max_value=5_000)
_NAME = st.text(max_size=30).filter(
    lambda value: value not in {"unblock", "renovation", "dynamic"}
)


@given(author_cost=st.integers(min_value=-1_000, max_value=10_000))
def test_dynamic_budget_is_clamped_to_documented_bounds(author_cost: int) -> None:
    budget = dynamic(author_cost)
    normalized = max(0, author_cost)

    assert budget.name == "dynamic"
    assert budget.max_changed_lines == min(300, max(5, round(normalized * 0.33)))
    assert budget.max_files == max(1, min(RENOVATION.max_files, budget.max_changed_lines))
    assert budget.max_outside_diff_lines == (
        0 if normalized <= 10 else min(50, floor(normalized * 0.05))
    )
    assert budget.max_risk == UNBLOCK.max_risk
    assert budget.allow_unsafe_fixes is False


@given(name=_NAME, author_cost=st.integers(min_value=-1_000, max_value=10_000))
def test_profile_unknown_names_fall_back_to_unblock(name: str, author_cost: int) -> None:
    assert profile(name, author_cost=author_cost) is UNBLOCK


@given(author_cost=st.integers(min_value=-1_000, max_value=10_000))
def test_profile_dynamic_uses_author_cost(author_cost: int) -> None:
    assert profile("dynamic", author_cost=author_cost) == dynamic(author_cost)


@given(name=st.sampled_from(["unblock", "renovation"]))
def test_profile_known_names_return_static_budget_profiles(name: str) -> None:
    expected = UNBLOCK if name == "unblock" else RENOVATION

    assert profile(name) is expected


@given(
    files_touched=_COUNT,
    changed_lines_total=_COUNT,
    changed_lines_outside_diff=_COUNT,
    risk=_COUNT,
    unsafe=st.booleans(),
    max_files=_COUNT,
    max_changed_lines=_COUNT,
    max_outside_diff_lines=_COUNT,
    max_risk=_COUNT,
    allow_unsafe_fixes=st.booleans(),
)
def test_check_budget_reports_first_exceeded_limit(
    files_touched: int,
    changed_lines_total: int,
    changed_lines_outside_diff: int,
    risk: int,
    unsafe: bool,
    max_files: int,
    max_changed_lines: int,
    max_outside_diff_lines: int,
    max_risk: int,
    allow_unsafe_fixes: bool,
) -> None:
    cost = CandidateCost(
        files_touched=files_touched,
        changed_lines_total=changed_lines_total,
        changed_lines_outside_diff=changed_lines_outside_diff,
        risk=risk,
        unsafe=unsafe,
    )
    budget = Budget(
        name="generated",
        max_files=max_files,
        max_changed_lines=max_changed_lines,
        max_outside_diff_lines=max_outside_diff_lines,
        max_risk=max_risk,
        allow_unsafe_fixes=allow_unsafe_fixes,
    )

    reason = check_budget(cost, budget)

    if unsafe and not allow_unsafe_fixes:
        assert reason == "unsafe fix not allowed"
    elif files_touched > max_files:
        assert reason == f"files {files_touched} > {max_files}"
    elif changed_lines_total > max_changed_lines:
        assert reason == f"changed lines {changed_lines_total} > {max_changed_lines}"
    elif changed_lines_outside_diff > max_outside_diff_lines:
        assert reason == (
            f"outside-diff lines {changed_lines_outside_diff} > {max_outside_diff_lines}"
        )
    elif risk > max_risk:
        assert reason == f"risk {risk} > {max_risk}"
    else:
        assert reason is None


@given(
    files_touched=_COUNT,
    changed_lines_total=_COUNT,
    changed_lines_outside_diff=_COUNT,
    risk=_COUNT,
    unsafe=st.booleans(),
)
def test_check_budget_accepts_values_at_their_limits_when_unsafe_is_allowed(
    files_touched: int,
    changed_lines_total: int,
    changed_lines_outside_diff: int,
    risk: int,
    unsafe: bool,
) -> None:
    cost = CandidateCost(
        files_touched=files_touched,
        changed_lines_total=changed_lines_total,
        changed_lines_outside_diff=changed_lines_outside_diff,
        risk=risk,
        unsafe=unsafe,
    )
    budget = Budget(
        name="generated",
        max_files=files_touched,
        max_changed_lines=changed_lines_total,
        max_outside_diff_lines=changed_lines_outside_diff,
        max_risk=risk,
        allow_unsafe_fixes=True,
    )

    assert check_budget(cost, budget) is None
