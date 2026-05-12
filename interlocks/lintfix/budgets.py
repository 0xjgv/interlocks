"""Budget definitions and checks for the rule-scoped fix harness.

Two profiles: ``unblock`` (tight, for support flow) and ``renovation`` (wider,
for chore PRs). ``check_budget`` returns ``None`` on pass or a string reason
on fail so the caller can surface a precise rejection message.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Budget:
    """A single budget profile."""

    name: str
    max_files: int
    max_changed_lines: int
    max_outside_diff_lines: int
    max_risk: int
    allow_unsafe_fixes: bool = False


UNBLOCK = Budget(
    name="unblock",
    max_files=5,
    max_changed_lines=80,
    max_outside_diff_lines=10,
    max_risk=8,
)

RENOVATION = Budget(
    name="renovation",
    max_files=50,
    max_changed_lines=2000,
    max_outside_diff_lines=2000,
    max_risk=30,
)

_PROFILES: dict[str, Budget] = {UNBLOCK.name: UNBLOCK, RENOVATION.name: RENOVATION}


def profile(name: str) -> Budget:
    """Return the budget profile by name. Defaults to ``unblock`` if unknown."""
    return _PROFILES.get(name, UNBLOCK)


@dataclass(frozen=True)
class CandidateCost:
    """Measured cost of one candidate patch."""

    files_touched: int
    changed_lines_total: int
    changed_lines_outside_diff: int
    risk: int
    unsafe: bool = False


def check_budget(cost: CandidateCost, budget: Budget) -> str | None:
    """Return ``None`` when ``cost`` fits ``budget``; else a short reason string."""
    if cost.unsafe and not budget.allow_unsafe_fixes:
        return "unsafe fix not allowed"
    if cost.files_touched > budget.max_files:
        return f"files {cost.files_touched} > {budget.max_files}"
    if cost.changed_lines_total > budget.max_changed_lines:
        return f"changed lines {cost.changed_lines_total} > {budget.max_changed_lines}"
    if cost.changed_lines_outside_diff > budget.max_outside_diff_lines:
        return (
            f"outside-diff lines {cost.changed_lines_outside_diff} > "
            f"{budget.max_outside_diff_lines}"
        )
    if cost.risk > budget.max_risk:
        return f"risk {cost.risk} > {budget.max_risk}"
    return None
