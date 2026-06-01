"""Property tests for lintfix optimizer invariants."""

from __future__ import annotations

import sys
from dataclasses import asdict
from typing import Any, cast

from hypothesis import given
from hypothesis import strategies as st

from interlocks.lintfix import plan as plan_module
from interlocks.lintfix.budgets import Budget, CandidateCost
from interlocks.lintfix.classify import CandidateMetrics, Classification
from interlocks.lintfix.optimize import (
    Candidate,
    CostVector,
    RejectedCandidate,
    SelectedCandidate,
    Selection,
    _budget_overflow,
    _build_selection,
    _dominates,
    _Plan,
    _prune_dominated,
    _rejection_reason,
    _search,
    _try_extend,
    candidates_from_plan,
    optimize,
)
from interlocks.lintfix.rules import Mode
from interlocks.lintfix.stats import RuleStats
from interlocks.lintfix.verify import BatchVerifyResult
from interlocks.tasks import fix_optimize as fix_optimize_mod


@st.composite
def candidates(draw: Any) -> tuple[Candidate, ...]:
    count = draw(st.integers(min_value=0, max_value=8))
    result: list[Candidate] = []
    for index in range(count):
        unsafe = draw(st.booleans())
        selectable = draw(st.booleans()) and not unsafe
        result.append(
            Candidate(
                rule=f"R{index}",
                value=draw(st.integers(min_value=1, max_value=100)),
                cost=CostVector(
                    outside_diff=draw(st.integers(min_value=0, max_value=20)),
                    changed_lines=draw(st.integers(min_value=0, max_value=100)),
                    files=1,
                    risk=draw(st.integers(min_value=0, max_value=20)),
                ),
                files=(f"file_{index}.py",),
                selectable=selectable,
                policy_mode="auto" if selectable else "escrow",
                unsafe=unsafe,
            )
        )
    return tuple(result)


_CANDIDATE = candidates().filter(bool).map(lambda items: items[0])
_RULE = st.from_regex(r"[A-Z][A-Z0-9]{1,5}", fullmatch=True)
_FILE = st.from_regex(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,20}\.py", fullmatch=True)
_KIND = st.sampled_from(["lint", "format", "other"])
_MODE = st.sampled_from(("auto", "escrow", "advisory", "skip"))
_ARG = st.text(
    alphabet=st.characters(blacklist_characters="\r\n"),
    min_size=1,
    max_size=20,
)


def _budget_for_all(items: tuple[Candidate, ...]) -> Budget:
    return Budget(
        name="generated",
        max_files=sum(item.cost.files for item in items),
        max_changed_lines=sum(item.cost.changed_lines for item in items),
        max_outside_diff_lines=sum(item.cost.outside_diff for item in items),
        max_risk=sum(item.cost.risk for item in items),
        allow_unsafe_fixes=False,
    )


@given(candidates())
def test_optimizer_selects_all_disjoint_selectable_candidates(
    items: tuple[Candidate, ...],
) -> None:
    selection = optimize(items, _budget_for_all(items))
    selected = tuple(item.candidate for item in selection.selected)

    assert selected == tuple(item for item in items if item.selectable)
    assert all(item.selectable for item in selected)
    assert {item.candidate for item in selection.selected}.isdisjoint({
        item.candidate for item in selection.rejected
    })


@given(candidates())
def test_optimizer_totals_match_selected_candidates(items: tuple[Candidate, ...]) -> None:
    selection = optimize(items, _budget_for_all(items))
    selected = tuple(item.candidate for item in selection.selected)

    assert selection.total_value == sum(item.value for item in selected)
    assert selection.total_cost == CostVector(
        outside_diff=sum(item.cost.outside_diff for item in selected),
        changed_lines=sum(item.cost.changed_lines for item in selected),
        files=sum(item.cost.files for item in selected),
        risk=sum(item.cost.risk for item in selected),
    )


@given(
    rule=_RULE,
    kind=_KIND,
    files=st.lists(_FILE, min_size=1, max_size=4, unique=True).map(tuple),
    diagnostic_count=st.integers(min_value=0, max_value=20),
)
def test_candidates_from_plan_projects_planned_candidate_fields(
    rule: str,
    kind: str,
    files: tuple[str, ...],
    diagnostic_count: int,
) -> None:
    planned = _planned(rule, kind=kind, files=files, diagnostic_count=diagnostic_count)

    [candidate] = candidates_from_plan((planned,))

    assert candidate.rule == rule
    assert candidate.files == files
    assert candidate.cost.files == len(files)
    assert candidate.cost.changed_lines == len(files)
    assert candidate.policy_mode == "auto"
    assert candidate.selectable
    assert candidate.kind == kind
    assert candidate.value >= 0


@given(
    mode=_MODE,
    candidate_unsafe=st.booleans(),
    stats_unsafe=st.booleans(),
    prs_helped=st.integers(min_value=0, max_value=20),
    diagnostic_count=st.integers(min_value=0, max_value=20),
)
def test_candidates_from_plan_applies_policy_safety_and_stats_support(
    mode: str,
    candidate_unsafe: bool,
    stats_unsafe: bool,
    prs_helped: int,
    diagnostic_count: int,
) -> None:
    planned = _planned(
        "F401",
        mode=cast("Mode", mode),
        unsafe=candidate_unsafe,
        diagnostic_count=diagnostic_count,
    )
    stats = _rule_stats("F401", prs_helped=prs_helped, unsafe_seen=stats_unsafe)

    [baseline] = candidates_from_plan((planned,))
    [candidate] = candidates_from_plan((planned,), {"F401": stats})

    assert candidate.selectable is (mode == "auto" and not candidate_unsafe)
    assert candidate.unsafe is candidate_unsafe
    if mode != "skip" and not stats_unsafe:
        assert candidate.value == baseline.value + (prs_helped * 5)
    else:
        assert candidate.value == baseline.value


@given(candidates())
def test_search_returns_only_budget_fitting_conflict_free_plans(
    items: tuple[Candidate, ...],
) -> None:
    budget = _budget_for_all(items)

    plans = _search(items, budget)

    assert plans
    for plan in plans:
        selected = [items[index] for index in plan.selected]
        assert plan.cost.outside_diff <= budget.max_outside_diff_lines
        assert plan.cost.changed_lines <= budget.max_changed_lines
        assert plan.cost.files <= budget.max_files
        assert plan.cost.risk <= budget.max_risk
        assert plan.value == sum(item.value for item in selected)
        flattened_files = [file for item in selected for file in item.files]
        assert len(flattened_files) == len(set(flattened_files))


@given(candidates())
def test_search_can_select_all_fitting_non_conflicting_candidates(
    items: tuple[Candidate, ...],
) -> None:
    budget = _budget_for_all(items)
    expected = frozenset(index for index, candidate in enumerate(items) if candidate.selectable)

    plans = _search(items, budget)

    assert any(plan.selected == expected for plan in plans)


@given(candidate=_CANDIDATE, overlaps=st.booleans())
def test_try_extend_rejects_conflicts_and_extends_fitting_candidates(
    candidate: Candidate,
    overlaps: bool,
) -> None:
    base_files = frozenset(candidate.files[:1]) if overlaps else frozenset()
    plan = _Plan(files=base_files)
    budget = _budget_for_all((candidate,))

    extended = _try_extend(plan, 0, candidate, budget)

    if overlaps and candidate.files:
        assert extended is None
    else:
        assert extended is not None
        assert extended.selected == frozenset({0})
        assert extended.value == candidate.value
        assert extended.cost == candidate.cost


@given(
    dimension=st.sampled_from(("outside_diff", "changed_lines", "files", "risk")),
    outside=st.integers(min_value=1, max_value=20),
    changed=st.integers(min_value=1, max_value=20),
    files=st.integers(min_value=1, max_value=5),
    risk=st.integers(min_value=1, max_value=20),
)
def test_try_extend_rejects_each_budget_dimension_overflow(
    dimension: str,
    outside: int,
    changed: int,
    files: int,
    risk: int,
) -> None:
    candidate = Candidate(
        rule="R0",
        value=1,
        cost=CostVector(outside_diff=outside, changed_lines=changed, files=files, risk=risk),
        files=tuple(f"file_{index}.py" for index in range(files)),
        selectable=True,
        policy_mode="auto",
    )
    budget_values = {
        "max_outside_diff_lines": outside,
        "max_changed_lines": changed,
        "max_files": files,
        "max_risk": risk,
    }
    budget_key = {
        "outside_diff": "max_outside_diff_lines",
        "changed_lines": "max_changed_lines",
        "files": "max_files",
        "risk": "max_risk",
    }[dimension]
    budget_values[budget_key] -= 1
    budget = Budget("generated", **budget_values)

    assert _try_extend(_Plan(), 0, candidate, budget) is None


@given(
    value=st.integers(min_value=0, max_value=100),
    outside=st.integers(min_value=0, max_value=20),
    changed=st.integers(min_value=0, max_value=20),
    files=st.integers(min_value=0, max_value=20),
    risk=st.integers(min_value=0, max_value=20),
)
def test_prune_dominated_drops_worse_equal_or_lower_value_plans(
    value: int,
    outside: int,
    changed: int,
    files: int,
    risk: int,
) -> None:
    cost = CostVector(outside, changed, files, risk)
    better = _Plan(selected=frozenset({0}), value=value + 1, cost=cost)
    worse = _Plan(
        selected=frozenset({1}),
        value=value,
        cost=CostVector(outside + 1, changed + 1, files + 1, risk + 1),
    )

    pruned = _prune_dominated([worse, better])

    assert better in pruned
    assert worse not in pruned
    assert _dominates(better, worse)


_PLAN = st.builds(
    _Plan,
    selected=st.frozensets(st.integers(min_value=0, max_value=20), max_size=4),
    value=st.integers(min_value=0, max_value=200),
    cost=st.builds(
        CostVector,
        outside_diff=st.integers(min_value=0, max_value=20),
        changed_lines=st.integers(min_value=0, max_value=50),
        files=st.integers(min_value=0, max_value=10),
        risk=st.integers(min_value=0, max_value=20),
    ),
    files=st.frozensets(_FILE, max_size=4),
)


@given(plans=st.lists(_PLAN, max_size=20))
def test_prune_dominated_is_idempotent_and_leaves_no_dominated_pairs(
    plans: list[_Plan],
) -> None:
    pruned = _prune_dominated(plans)

    assert _prune_dominated(pruned) == pruned
    for index, left in enumerate(pruned):
        for right in pruned[index + 1 :]:
            assert not _dominates(left, right)
            assert not _dominates(right, left)


@given(
    items=candidates(),
    selected_indices=st.sets(st.integers(min_value=0, max_value=7), max_size=8),
)
def test_build_selection_partitions_candidates_by_best_plan(
    items: tuple[Candidate, ...],
    selected_indices: set[int],
) -> None:
    selected = frozenset(index for index in selected_indices if index < len(items))
    best = _Plan(
        selected=selected,
        value=sum(items[index].value for index in selected),
        cost=CostVector(
            outside_diff=sum(items[index].cost.outside_diff for index in selected),
            changed_lines=sum(items[index].cost.changed_lines for index in selected),
            files=sum(items[index].cost.files for index in selected),
            risk=sum(items[index].cost.risk for index in selected),
        ),
    )
    budget = _budget_for_all(items)

    selection = _build_selection(items, budget, best)

    assert [entry.candidate for entry in selection.selected] == [
        items[index] for index in sorted(selected)
    ]
    assert [entry.candidate for entry in selection.rejected] == [
        item for index, item in enumerate(items) if index not in selected
    ]
    assert selection.total_value == best.value
    assert selection.total_cost == best.cost


@given(dimension=st.sampled_from(["outside", "changed", "files", "risk", "none"]))
def test_budget_overflow_reports_first_exceeded_dimension(dimension: str) -> None:
    budget = Budget("tiny", max_files=1, max_changed_lines=1, max_outside_diff_lines=1, max_risk=1)
    values = {
        "outside_diff": 1,
        "changed_lines": 1,
        "files": 1,
        "risk": 1,
    }
    if dimension == "outside":
        values["outside_diff"] = 2
    elif dimension == "changed":
        values["changed_lines"] = 2
    elif dimension == "files":
        values["files"] = 2
    elif dimension == "risk":
        values["risk"] = 2
    candidate = _candidate(
        "R0",
        files=("sample.py",) * values["files"],
        value=1,
    )
    candidate = Candidate(
        rule=candidate.rule,
        value=candidate.value,
        cost=CostVector(**values),
        files=candidate.files,
        selectable=True,
        policy_mode="auto",
    )

    overflow = _budget_overflow(candidate, _Plan(), budget)

    assert (
        overflow
        == {
            "outside": "outside-author-hunk",
            "changed": "total changed-lines",
            "files": "files",
            "risk": "risk",
            "none": None,
        }[dimension]
    )


def test_rejection_reason_reports_unsafe_policy_conflict_budget_or_displacement() -> None:
    budget = Budget("tiny", max_files=2, max_changed_lines=2, max_outside_diff_lines=1, max_risk=2)
    selected = _candidate("R0", files=("same.py",), value=10)
    unsafe = Candidate(**{
        **selected.__dict__,
        "rule": "R1",
        "unsafe": True,
        "files": ("unsafe.py",),
    })
    policy = Candidate(**{
        **selected.__dict__,
        "rule": "R2",
        "selectable": False,
        "policy_mode": "escrow",
        "files": ("policy.py",),
    })
    conflict = _candidate("R3", files=("same.py",), value=1)
    over_budget = Candidate(**{
        **selected.__dict__,
        "rule": "R4",
        "cost": CostVector(outside_diff=2, changed_lines=1, files=1, risk=1),
        "files": ("over.py",),
    })
    displaced = _candidate("R5", files=("other.py",), value=1)
    candidates = (selected, unsafe, policy, conflict, over_budget, displaced)
    best = _Plan(selected=frozenset({0}), value=selected.value, cost=selected.cost)

    assert (
        _rejection_reason(unsafe, candidates, best, budget) == "unsafe fix not allowed by budget"
    )
    assert _rejection_reason(policy, candidates, best, budget) == "policy mode is escrow"
    assert _rejection_reason(conflict, candidates, best, budget) == (
        "conflicts with selected candidate R0"
    )
    assert _rejection_reason(over_budget, candidates, best, budget) == (
        "would exceed outside-author-hunk budget"
    )
    assert _rejection_reason(displaced, candidates, best, budget) == (
        "displaced by higher-value selection"
    )


def _metrics(files: tuple[str, ...]) -> CandidateMetrics:
    return CandidateMetrics(
        files_touched=files,
        changed_lines_total=len(files),
        changed_lines_inside_diff=len(files),
        changed_lines_outside_diff=0,
        comment_deletes=0,
        control_flow_edits=0,
    )


def _planned(
    rule: str,
    *,
    kind: str = "lint",
    files: tuple[str, ...] = ("sample.py",),
    diagnostic_count: int = 1,
    mode: Mode = "auto",
    unsafe: bool = False,
) -> plan_module.PlannedCandidate:
    return plan_module.PlannedCandidate(
        classification=Classification(
            rule=rule,
            mode=mode,
            metrics=_metrics(files),
            cost=CandidateCost(
                files_touched=len(files),
                changed_lines_total=len(files),
                changed_lines_outside_diff=0,
                risk=0,
            ),
            reason=None,
            patch_id=rule,
        ),
        diff_text=f"diff-{rule}",
        unsafe=unsafe,
        diagnostic_count=diagnostic_count,
        mutation_class="other",
        kind=kind,
    )


def _candidate(
    rule: str,
    *,
    kind: str = "lint",
    files: tuple[str, ...] = ("sample.py",),
    value: int = 1,
) -> Candidate:
    return Candidate(
        rule=rule,
        value=value,
        cost=CostVector(outside_diff=0, changed_lines=len(files), files=len(files), risk=0),
        files=files,
        selectable=True,
        policy_mode="auto",
        unsafe=False,
        kind=kind,
    )


def _rule_stats(rule: str, *, prs_helped: int, unsafe_seen: bool) -> RuleStats:
    return RuleStats(
        rule=rule,
        mutation_class="other",
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


def _selection(
    *,
    selected: tuple[Candidate, ...],
    rejected: tuple[tuple[Candidate, str], ...] = (),
) -> Selection:
    total_cost = CostVector(
        outside_diff=sum(item.cost.outside_diff for item in selected),
        changed_lines=sum(item.cost.changed_lines for item in selected),
        files=sum(item.cost.files for item in selected),
        risk=sum(item.cost.risk for item in selected),
    )
    return Selection(
        budget_name="unblock",
        selected=tuple(SelectedCandidate(candidate=item) for item in selected),
        rejected=tuple(
            RejectedCandidate(candidate=item, reason=reason) for item, reason in rejected
        ),
        total_value=sum(item.value for item in selected),
        total_cost=total_cost,
    )


@given(
    explicit=st.one_of(st.none(), _ARG),
    no_stats=st.booleans(),
)
def test_resolve_stats_path_prefers_explicit_then_no_stats(
    explicit: str | None,
    no_stats: bool,
) -> None:
    argv = ["interlocks", "fix-optimize"]
    if explicit is not None:
        argv.append(f"--stats={explicit}")
    if no_stats:
        argv.append("--no-stats")
    old_argv = sys.argv
    sys.argv = argv
    try:
        resolved = fix_optimize_mod._resolve_stats_path()
    finally:
        sys.argv = old_argv

    if explicit is not None:
        assert resolved == explicit
    elif no_stats:
        assert not resolved
    else:
        assert resolved == ".lintfix/replay.json"


@given(
    rows=st.lists(
        st.tuples(
            _RULE,
            _KIND,
            st.lists(_FILE, min_size=1, max_size=3, unique=True).map(tuple),
        ),
        max_size=8,
        unique_by=lambda row: row[0],
    )
)
def test_selected_candidates_project_selection_through_plan_by_rule(
    rows: list[tuple[str, str, tuple[str, ...]]],
) -> None:
    plan_by_rule = {rule: _planned(rule, kind=kind, files=files) for rule, kind, files in rows}
    selection = _selection(
        selected=tuple(_candidate(rule, kind=kind, files=files) for rule, kind, files in rows)
    )

    assert fix_optimize_mod._selected_candidates(plan_by_rule, selection) == tuple(
        (kind, rule, files) for rule, kind, files in rows
    )


@given(
    rule=_RULE,
    kind=_KIND,
    files=st.lists(_FILE, min_size=1, max_size=4, unique=True).map(tuple),
    value=st.integers(min_value=0, max_value=1_000),
    diagnostic_count=st.integers(min_value=0, max_value=100),
    has_patch_path=st.booleans(),
    has_plan=st.booleans(),
    reason=st.one_of(st.none(), st.text(max_size=30)),
)
def test_serialize_candidate_uses_candidate_and_optional_plan_snapshot(
    rule: str,
    kind: str,
    files: tuple[str, ...],
    value: int,
    diagnostic_count: int,
    has_patch_path: bool,
    has_plan: bool,
    reason: str | None,
) -> None:
    candidate = _candidate(rule, kind=kind, files=files, value=value)
    patch_paths = {rule: f".lintfix/{rule}.patch"} if has_patch_path else {}
    plan_by_rule = (
        {rule: _planned(rule, kind=kind, files=files, diagnostic_count=diagnostic_count)}
        if has_plan
        else {}
    )

    payload = fix_optimize_mod._serialize_candidate(
        candidate,
        patch_paths,
        plan_by_rule,
        reason=reason,
    )

    assert payload == {
        "rule": rule,
        "value": value,
        "cost": asdict(candidate.cost),
        "policy_mode": "auto",
        "kind": kind,
        "unsafe": False,
        "files": list(files),
        "patch_path": patch_paths.get(rule),
        "reason": reason,
        "diagnostic_count": diagnostic_count if has_plan else 0,
    }


@given(
    selected_rows=st.lists(
        st.tuples(_RULE, _KIND, st.lists(_FILE, min_size=1, max_size=3, unique=True).map(tuple)),
        max_size=5,
        unique_by=lambda row: row[0],
    ),
    rejected_rows=st.lists(
        st.tuples(
            _RULE,
            _KIND,
            st.lists(_FILE, min_size=1, max_size=3, unique=True).map(tuple),
            st.text(max_size=20),
        ),
        max_size=5,
        unique_by=lambda row: row[0],
    ),
)
def test_serialize_preserves_selected_and_rejected_candidate_order(
    selected_rows: list[tuple[str, str, tuple[str, ...]]],
    rejected_rows: list[tuple[str, str, tuple[str, ...], str]],
) -> None:
    selected_rules = {rule for rule, _kind, _files in selected_rows}
    rejected_rows = [row for row in rejected_rows if row[0] not in selected_rules]
    all_rows = [
        (rule, kind, files) for rule, kind, files in selected_rows for _unused in (None,)
    ] + [(rule, kind, files) for rule, kind, files, _reason in rejected_rows]
    plan_by_rule = {rule: _planned(rule, kind=kind, files=files) for rule, kind, files in all_rows}
    selected = tuple(
        _candidate(rule, kind=kind, files=files, value=index + 1)
        for index, (rule, kind, files) in enumerate(selected_rows)
    )
    rejected = tuple(
        (
            _candidate(rule, kind=kind, files=files, value=index + 1),
            reason,
        )
        for index, (rule, kind, files, reason) in enumerate(rejected_rows)
    )
    selection = _selection(selected=selected, rejected=rejected)
    plan = plan_module.Plan(
        base="HEAD",
        head="abc123",
        budget="unblock",
        ruff_version="0.x",
        candidates=tuple(plan_by_rule.values()),
        discovery_error=None,
        author_cost=3,
    )

    payload = fix_optimize_mod._serialize(
        plan,
        selection,
        {rule: f".lintfix/{rule}.patch" for rule in plan_by_rule},
        plan_by_rule,
    )

    assert payload["base"] == "HEAD"
    assert payload["head"] == "abc123"
    assert payload["budget"] == "unblock"
    assert payload["author_cost"] == 3
    assert payload["ruff_version"] == "0.x"
    assert payload["total_value"] == selection.total_value
    assert payload["total_cost"] == asdict(selection.total_cost)
    assert [entry["rule"] for entry in payload["selected"]] == [
        rule for rule, _kind, _files in selected_rows
    ]
    assert [entry["rule"] for entry in payload["not_selected"]] == [
        rule for rule, _kind, _files, _reason in rejected_rows
    ]
    assert [entry["reason"] for entry in payload["not_selected"]] == [
        reason for _rule, _kind, _files, reason in rejected_rows
    ]


@given(
    selected_rows=st.lists(
        st.tuples(_RULE, _KIND, st.lists(_FILE, min_size=1, max_size=3, unique=True).map(tuple)),
        max_size=5,
        unique_by=lambda row: row[0],
    ),
    requested=st.booleans(),
    exit_code=st.one_of(st.none(), st.integers(min_value=0, max_value=10)),
)
def test_fix_optimize_apply_payload_reports_request_and_failure_state(
    selected_rows: list[tuple[str, str, tuple[str, ...]]],
    requested: bool,
    exit_code: int | None,
) -> None:
    selection = _selection(
        selected=tuple(
            _candidate(rule, kind=kind, files=files) for rule, kind, files in selected_rows
        )
    )

    payload = fix_optimize_mod._apply_payload(selection, requested, exit_code)

    assert payload["requested"] is requested
    if not requested:
        assert payload == {"requested": False, "status": "not-requested"}
    elif exit_code not in (None, 0):
        assert payload["status"] == "failed"
        assert payload["returncode"] == exit_code
        assert payload["failed_patch"] == ".lintfix/failed.patch"
    elif selected_rows:
        assert payload["status"] == "applied"
        assert payload["selected_rules"] == [rule for rule, _kind, _files in selected_rows]
    else:
        assert payload["status"] == "nothing-to-apply"
        assert payload["selected_rules"] == []


@given(
    selected_rows=st.lists(
        st.tuples(_RULE, _KIND, st.lists(_FILE, min_size=1, max_size=3, unique=True).map(tuple)),
        min_size=1,
        max_size=5,
        unique_by=lambda row: row[0],
    ),
    exit_code=st.integers(min_value=1, max_value=127),
)
def test_fix_optimize_apply_payload_preserves_failed_selection_context(
    selected_rows: list[tuple[str, str, tuple[str, ...]]],
    exit_code: int,
) -> None:
    selection = _selection(
        selected=tuple(
            _candidate(rule, kind=kind, files=files) for rule, kind, files in selected_rows
        )
    )

    payload = fix_optimize_mod._apply_payload(selection, True, exit_code)

    assert payload["status"] == "failed"
    assert payload["selected_rules"] == [rule for rule, _kind, _files in selected_rows]
    assert payload["returncode"] == exit_code
    assert payload["failed_patch"] == ".lintfix/failed.patch"


@given(
    stderr=st.text(),
    limit=st.integers(min_value=1, max_value=80),
)
def test_fix_optimize_stderr_excerpt_strips_and_caps(stderr: str, limit: int) -> None:
    excerpt = fix_optimize_mod._stderr_excerpt(stderr, limit=limit)
    cleaned = stderr.strip()

    assert len(excerpt) <= limit
    if len(cleaned) <= limit:
        assert excerpt == cleaned
    else:
        assert excerpt == cleaned[: limit - 1] + "\u2026"


@given(
    rows=st.lists(
        st.tuples(
            st.sampled_from(["lint", "format", "other"]),
            _RULE,
            st.lists(_FILE, min_size=1, max_size=3, unique=True).map(tuple),
        ),
        max_size=8,
    ),
    verify_cmd=st.lists(st.text(min_size=1, max_size=12), min_size=1, max_size=4).map(tuple),
)
def test_apply_candidates_dispatches_lint_only_batches_to_lint_apply_path(
    rows: list[tuple[str, str, tuple[str, ...]]],
    verify_cmd: tuple[str, ...],
) -> None:
    candidates = tuple(rows)
    calls: list[tuple[str, object, tuple[str, ...]]] = []
    result = BatchVerifyResult(True, 0, "", "", restored=False, applied_rules=())

    def fake_lint_apply(
        *,
        rules_and_files: tuple[tuple[str, tuple[str, ...]], ...],
        verify_cmd: tuple[str, ...],
    ) -> BatchVerifyResult:
        calls.append(("lint", rules_and_files, verify_cmd))
        return result

    def fake_candidate_apply(
        *,
        candidates: tuple[tuple[str, str, tuple[str, ...]], ...],
        verify_cmd: tuple[str, ...],
    ) -> BatchVerifyResult:
        calls.append(("candidate", candidates, verify_cmd))
        return result

    old_lint = fix_optimize_mod.verify.apply_many_with_verify
    old_candidate = fix_optimize_mod.verify.apply_many_candidates_with_verify
    fix_optimize_mod.verify.apply_many_with_verify = fake_lint_apply  # type: ignore[assignment]
    fix_optimize_mod.verify.apply_many_candidates_with_verify = fake_candidate_apply  # type: ignore[assignment]
    try:
        returned = fix_optimize_mod._apply_candidates(candidates, verify_cmd)
    finally:
        fix_optimize_mod.verify.apply_many_with_verify = old_lint
        fix_optimize_mod.verify.apply_many_candidates_with_verify = old_candidate

    assert returned is result
    if all(kind == "lint" for kind, _rule, _files in candidates):
        assert calls == [
            (
                "lint",
                tuple((rule, files) for _kind, rule, files in candidates),
                verify_cmd,
            )
        ]
    else:
        assert calls == [("candidate", candidates, verify_cmd)]
