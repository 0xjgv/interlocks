"""Budgeted candidate subset selection (Phase 4).

Takes the candidate patches produced by :mod:`lintfix.plan` and chooses the
subset that maximizes total value under a multi-dimensional budget, using a
small Pareto-pruned dynamic-programming search.

Design notes
------------

- Only ``auto`` candidates are selectable. ``escrow``/``advisory``/``skip``
  candidates appear in the rejection list with a policy-mode reason so the
  output stays explainable but the harness never silently applies a rule
  outside its policy mode.
- The value function is the deterministic baseline from SPEC §11.2; replay
  stats (when available) add a "repeated support pattern" component.
- Initial conflict detection is conservative: two candidates that touch any
  shared file are flagged as conflicting. With that rule the cost-files sum
  equals the size of the union, so summing is exact (not an upper bound).
- The Pareto frontier discards plans dominated in every cost dimension by a
  plan of at least equal value. With candidate counts in the low double
  digits the frontier stays tiny in practice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from interlocks.lintfix.budgets import Budget
    from interlocks.lintfix.plan import PlannedCandidate
    from interlocks.lintfix.stats import RuleStats


@dataclass(frozen=True)
class CostVector:
    """Four scalar cost dimensions tracked during DP."""

    outside_diff: int
    changed_lines: int
    files: int
    risk: int

    def __add__(self, other: CostVector) -> CostVector:
        return CostVector(
            outside_diff=self.outside_diff + other.outside_diff,
            changed_lines=self.changed_lines + other.changed_lines,
            files=self.files + other.files,
            risk=self.risk + other.risk,
        )


@dataclass(frozen=True)
class Candidate:
    """One optimizer input. Decoupled from :class:`PlannedCandidate` so the
    optimizer is testable from synthetic data without building a full plan."""

    rule: str
    value: int
    cost: CostVector
    files: tuple[str, ...]
    selectable: bool
    policy_mode: str
    unsafe: bool = False


@dataclass(frozen=True)
class SelectedCandidate:
    """A candidate that the optimizer chose."""

    candidate: Candidate


@dataclass(frozen=True)
class RejectedCandidate:
    """A candidate the optimizer did not choose, with a one-line reason."""

    candidate: Candidate
    reason: str


@dataclass(frozen=True)
class Selection:
    """Final optimizer result."""

    budget_name: str
    selected: tuple[SelectedCandidate, ...]
    rejected: tuple[RejectedCandidate, ...]
    total_value: int
    total_cost: CostVector


# --- Value function -------------------------------------------------------

_FINDINGS_WEIGHT = 8
_SUPPORT_WEIGHT = 5
_NOISE_WEIGHT = 3
_ADVISORY_PENALTY = 2


def value_for(planned: PlannedCandidate, stats: RuleStats | None = None) -> int:
    """Compute the deterministic value for one planned candidate.

    Follows SPEC §11.2 with the bits we can measure today:

    * ``changed_line_findings_fixed`` is approximated by ``diagnostic_count``
      from ruff's discovery JSON.
    * ``repeated_support_pattern_score`` is sourced from ``stats.prs_helped``
      when replay data is provided; an unsafe-seen rule contributes zero.
    * ``review_noise_reduction_score`` rewards patches that concentrate inside
      the diff over outside-diff churn.
    * ``advisory_style_only_penalty`` deducts 2 from any advisory candidate.
    * ``known_bug_contracts_fixed`` is zero until we wire an incident map.
    """
    if planned.classification.mode == "skip":
        return 0
    findings = _FINDINGS_WEIGHT * planned.diagnostic_count
    support = _SUPPORT_WEIGHT * _support_score(stats)
    metrics = planned.classification.metrics
    inside_excess = max(0, metrics.changed_lines_inside_diff - metrics.changed_lines_outside_diff)
    noise = _NOISE_WEIGHT * inside_excess
    penalty = _ADVISORY_PENALTY if planned.classification.mode == "advisory" else 0
    return max(0, findings + support + noise - penalty)


def _support_score(stats: RuleStats | None) -> int:
    if stats is None or stats.unsafe_seen:
        return 0
    return stats.prs_helped


# --- Candidate construction ----------------------------------------------


def candidates_from_plan(
    planned: Iterable[PlannedCandidate],
    stats: Mapping[str, RuleStats] | None = None,
) -> tuple[Candidate, ...]:
    """Map planner output + optional replay stats to optimizer candidates."""
    stats = stats or {}
    out: list[Candidate] = []
    for p in planned:
        cls = p.classification
        metrics = cls.metrics
        out.append(
            Candidate(
                rule=cls.rule,
                value=value_for(p, stats.get(cls.rule)),
                cost=CostVector(
                    outside_diff=metrics.changed_lines_outside_diff,
                    changed_lines=metrics.changed_lines_total,
                    files=len(metrics.files_touched),
                    risk=cls.cost.risk,
                ),
                files=metrics.files_touched,
                selectable=(cls.mode == "auto" and not p.unsafe),
                policy_mode=cls.mode,
                unsafe=p.unsafe,
            )
        )
    return tuple(out)


# --- Conflict detection ---------------------------------------------------


def conflicts(a: Candidate, b: Candidate) -> bool:
    """Conservative: two candidates conflict if they touch any shared file."""
    return bool(set(a.files) & set(b.files))


# --- DP search ------------------------------------------------------------


@dataclass(frozen=True)
class _Plan:
    selected: frozenset[int] = field(default_factory=frozenset)
    value: int = 0
    cost: CostVector = field(default_factory=lambda: CostVector(0, 0, 0, 0))
    files: frozenset[str] = field(default_factory=frozenset)


def optimize(candidates: tuple[Candidate, ...], budget: Budget) -> Selection:
    """Choose a max-value subset under ``budget`` with conservative conflicts."""
    plans = _search(candidates, budget)
    best = max(plans, key=lambda p: (p.value, -p.cost.risk, -p.cost.outside_diff))
    return _build_selection(candidates, budget, best)


def _search(candidates: tuple[Candidate, ...], budget: Budget) -> list[_Plan]:
    """Run Pareto-pruned 0/1-knapsack-style DP."""
    plans: list[_Plan] = [_Plan()]
    for idx, candidate in enumerate(candidates):
        if not candidate.selectable:
            continue
        next_plans = list(plans)
        for plan in plans:
            extended = _try_extend(plan, idx, candidate, budget)
            if extended is not None:
                next_plans.append(extended)
        plans = _prune_dominated(next_plans)
    return plans


def _try_extend(plan: _Plan, idx: int, candidate: Candidate, budget: Budget) -> _Plan | None:
    if plan.files & frozenset(candidate.files):
        return None
    new_cost = plan.cost + candidate.cost
    if (
        new_cost.outside_diff > budget.max_outside_diff_lines
        or new_cost.changed_lines > budget.max_changed_lines
        or new_cost.files > budget.max_files
        or new_cost.risk > budget.max_risk
    ):
        return None
    return _Plan(
        selected=plan.selected | {idx},
        value=plan.value + candidate.value,
        cost=new_cost,
        files=plan.files | frozenset(candidate.files),
    )


def _prune_dominated(plans: list[_Plan]) -> list[_Plan]:
    """Drop plans dominated by another plan with equal or higher value."""
    # Sort by value desc so a plan can only be dominated by an earlier entry.
    ordered = sorted(plans, key=lambda p: -p.value)
    kept: list[_Plan] = []
    for plan in ordered:
        if not any(_dominates(other, plan) for other in kept):
            kept.append(plan)
    return kept


def _dominates(a: _Plan, b: _Plan) -> bool:
    """Does ``a`` dominate ``b``? Equal-value plans with equal cost dedup
    via this path: the second-seen plan is dropped."""
    if a.selected == b.selected:
        return False  # same plan; let the caller keep one of them
    if a.value < b.value:
        return False
    cost_le = (
        a.cost.outside_diff <= b.cost.outside_diff
        and a.cost.changed_lines <= b.cost.changed_lines
        and a.cost.files <= b.cost.files
        and a.cost.risk <= b.cost.risk
    )
    if not cost_le:
        return False
    strictly_better_value = a.value > b.value
    strictly_better_cost = (
        a.cost.outside_diff < b.cost.outside_diff
        or a.cost.changed_lines < b.cost.changed_lines
        or a.cost.files < b.cost.files
        or a.cost.risk < b.cost.risk
    )
    return strictly_better_value or strictly_better_cost


# --- Selection assembly ---------------------------------------------------


def _build_selection(candidates: tuple[Candidate, ...], budget: Budget, best: _Plan) -> Selection:
    selected_indices = best.selected
    selected = tuple(SelectedCandidate(candidate=candidates[i]) for i in sorted(selected_indices))
    rejected = tuple(
        RejectedCandidate(
            candidate=candidates[i],
            reason=_rejection_reason(candidates[i], candidates, best, budget),
        )
        for i in range(len(candidates))
        if i not in selected_indices
    )
    return Selection(
        budget_name=budget.name,
        selected=selected,
        rejected=rejected,
        total_value=best.value,
        total_cost=best.cost,
    )


def _rejection_reason(
    candidate: Candidate,
    candidates: tuple[Candidate, ...],
    best: _Plan,
    budget: Budget,
) -> str:
    """Explain why ``candidate`` was not selected, given the optimal plan."""
    if candidate.unsafe:
        return "unsafe fix not allowed by budget"
    if not candidate.selectable:
        return f"policy mode is {candidate.policy_mode}"
    blocker = next(
        (candidates[i].rule for i in best.selected if conflicts(candidates[i], candidate)),
        None,
    )
    if blocker is not None:
        return f"conflicts with selected rule {blocker}"
    over = _budget_overflow(candidate, best, budget)
    if over is not None:
        return f"would exceed {over} budget"
    return "displaced by higher-value selection"


def _budget_overflow(candidate: Candidate, best: _Plan, budget: Budget) -> str | None:
    """If adding ``candidate`` to ``best`` would bust a budget, return its name."""
    combined = best.cost + candidate.cost
    if combined.outside_diff > budget.max_outside_diff_lines:
        return "outside-diff"
    if combined.changed_lines > budget.max_changed_lines:
        return "changed-lines"
    if combined.files > budget.max_files:
        return "files"
    if combined.risk > budget.max_risk:
        return "risk"
    return None
