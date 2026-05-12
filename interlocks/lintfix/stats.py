"""Per-rule statistics and Pareto-frontier analysis for replayed plans.

Consumes one :class:`CandidateSample` per (commit, rule) observation and
produces a :class:`RuleStats` table plus a recommended mode per rule. The
mode recommendation enforces the Phase 3 acceptance rule: a "broad style
family" reached via prefix fallback cannot be promoted to ``auto`` on the
same evidence threshold as an exact-catalog code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from interlocks.lintfix.rules import Mode, known_rules, policy_for

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

# Promotion floors — below these, recommend "needs_data" regardless of fit.
_MIN_OBS_EXACT = 3
_MIN_OBS_PREFIX = 10

# Churn ceilings — at or below ``_PROMOTE_OUTSIDE_DIFF_MAX``, a rule can stay
# (or move to) auto. Above ``_DEMOTE_OUTSIDE_DIFF_MIN``, an auto rule is
# demoted to escrow.
_PROMOTE_OUTSIDE_DIFF_MAX = 5
_DEMOTE_OUTSIDE_DIFF_MIN = 20


@dataclass(frozen=True)
class CandidateSample:
    """One per-commit candidate observation from a replayed plan."""

    rule: str
    mutation_class: str
    classification: Mode
    changed_lines_total: int
    changed_lines_outside_diff: int
    risk: int
    unsafe: bool
    commit: str
    reverted_in: str | None


@dataclass(frozen=True)
class RuleStats:
    """Aggregate stats for one rule across the replay window."""

    rule: str
    mutation_class: str
    current_mode: Mode
    prs_with_candidate: int
    prs_helped: int
    median_changed_lines: float
    p95_changed_lines: float
    median_outside_diff_lines: float
    p95_outside_diff_lines: float
    unsafe_seen: bool
    revert_signal: int
    on_pareto_frontier: bool
    recommended_mode: Mode | str
    rationale: str


def aggregate(samples: Iterable[CandidateSample]) -> tuple[RuleStats, ...]:
    """Aggregate per-(commit, rule) samples into one :class:`RuleStats` per rule.

    ``prs_helped`` counts observations whose classification is not ``skip``;
    that mirrors the planner's own filter for what would actually fix code.
    """
    grouped: dict[str, list[CandidateSample]] = {}
    for s in samples:
        grouped.setdefault(s.rule, []).append(s)

    raw_stats = [_aggregate_one(rule, obs) for rule, obs in grouped.items()]
    frontier = _pareto_frontier(raw_stats)
    return tuple(_with_recommendation(s, on_frontier=(s.rule in frontier)) for s in raw_stats)


def _aggregate_one(rule: str, observations: Sequence[CandidateSample]) -> RuleStats:
    policy = policy_for(rule)
    total_lines = [o.changed_lines_total for o in observations]
    outside = [o.changed_lines_outside_diff for o in observations]
    helped = sum(1 for o in observations if o.classification != "skip")
    return RuleStats(
        rule=rule,
        mutation_class=policy.mutation_class,
        current_mode=policy.mode,
        prs_with_candidate=len(observations),
        prs_helped=helped,
        median_changed_lines=quantile(total_lines, 0.5),
        p95_changed_lines=quantile(total_lines, 0.95),
        median_outside_diff_lines=quantile(outside, 0.5),
        p95_outside_diff_lines=quantile(outside, 0.95),
        unsafe_seen=any(o.unsafe for o in observations),
        revert_signal=sum(1 for o in observations if o.reverted_in is not None),
        on_pareto_frontier=False,
        recommended_mode=policy.mode,
        rationale="",
    )


def quantile(values: Sequence[int], q: float) -> float:
    """Linear-interpolation quantile. Empty input returns ``0.0``.

    Matches the spec's "median/p95 changed_lines" requirement without a numpy
    dep. Behaves like ``numpy.quantile(..., method="linear")`` on the values.
    """
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


def _pareto_frontier(stats: Sequence[RuleStats]) -> frozenset[str]:
    """Return the set of rule codes that are not dominated by any other rule.

    Value axis (maximize): ``prs_helped``.
    Cost axis (minimize):  ``p95_outside_diff_lines``.

    A rule that has ever produced an unsafe candidate can only be dominated
    by another also-unsafe rule — we don't want an unsafe rule to push a safe
    rule off the frontier.
    """
    frontier: set[str] = set()
    for candidate in stats:
        dominated = any(
            _dominates(other, candidate) for other in stats if other.rule != candidate.rule
        )
        if not dominated:
            frontier.add(candidate.rule)
    return frozenset(frontier)


def _dominates(a: RuleStats, b: RuleStats) -> bool:
    """Does ``a`` strictly dominate ``b``? (a is at least as good everywhere, better somewhere)."""
    if a.unsafe_seen and not b.unsafe_seen:
        return False
    helped_ge = a.prs_helped >= b.prs_helped
    cost_le = a.p95_outside_diff_lines <= b.p95_outside_diff_lines
    strict = a.prs_helped > b.prs_helped or a.p95_outside_diff_lines < b.p95_outside_diff_lines
    return helped_ge and cost_le and strict


def _with_recommendation(stats: RuleStats, *, on_frontier: bool) -> RuleStats:
    mode, rationale = _recommend(stats, on_frontier=on_frontier)
    return RuleStats(
        rule=stats.rule,
        mutation_class=stats.mutation_class,
        current_mode=stats.current_mode,
        prs_with_candidate=stats.prs_with_candidate,
        prs_helped=stats.prs_helped,
        median_changed_lines=stats.median_changed_lines,
        p95_changed_lines=stats.p95_changed_lines,
        median_outside_diff_lines=stats.median_outside_diff_lines,
        p95_outside_diff_lines=stats.p95_outside_diff_lines,
        unsafe_seen=stats.unsafe_seen,
        revert_signal=stats.revert_signal,
        on_pareto_frontier=on_frontier,
        recommended_mode=mode,
        rationale=rationale,
    )


def _recommend(stats: RuleStats, *, on_frontier: bool) -> tuple[Mode | str, str]:
    """Decide a recommended mode + one-line rationale.

    Exact catalog codes (``rules.known_rules()``) can move escrow→auto on the
    standard floor of ``_MIN_OBS_EXACT`` observations. Prefix-fallback codes
    need ``_MIN_OBS_PREFIX`` AND must already be on the Pareto frontier;
    this satisfies acceptance criterion 2 ("broad style families cannot
    enter auto mode without evidence").
    """
    exact = stats.rule in known_rules()
    floor = _MIN_OBS_EXACT if exact else _MIN_OBS_PREFIX
    p95 = stats.p95_outside_diff_lines

    decision: tuple[Mode | str, str] = (stats.current_mode, "stays at current mode")

    if stats.unsafe_seen:
        decision = ("skip", "unsafe candidate observed during replay")
    elif stats.prs_with_candidate < floor:
        decision = ("needs_data", f"only {stats.prs_with_candidate} observations (floor={floor})")
    elif stats.revert_signal > 0 and stats.current_mode == "auto":
        decision = ("escrow", f"{stats.revert_signal} reverted PR(s) — demote from auto")
    elif p95 > _DEMOTE_OUTSIDE_DIFF_MIN:
        if stats.current_mode == "auto":
            decision = (
                "escrow",
                f"p95 outside-diff={p95:g} > {_DEMOTE_OUTSIDE_DIFF_MIN} — demote",
            )
        else:
            decision = (stats.current_mode, f"churn too high (p95 outside-diff={p95:g})")
    elif (
        on_frontier
        and p95 <= _PROMOTE_OUTSIDE_DIFF_MAX
        and stats.revert_signal == 0
        and stats.current_mode == "escrow"
    ):
        decision = (
            ("auto", f"on frontier; p95 outside-diff={p95:g} ≤ {_PROMOTE_OUTSIDE_DIFF_MAX}")
            if exact
            else ("escrow", "prefix-fallback rule: needs explicit catalog entry before promotion")
        )

    return decision
