"""Property tests for fix-replay summary grouping."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from hypothesis import given
from hypothesis import strategies as st

from interlocks.lintfix.replay import ReplayPoint, ReplayResult
from interlocks.lintfix.stats import RuleStats
from interlocks.tasks.fix_replay import (
    _bucket,
    _fix_replay_payload,
    _group_rule_stats,
    _pareto_frontier,
    _rule_sort_key,
    _serialize,
)

if TYPE_CHECKING:
    from interlocks.lintfix.rules import Mode

_MODE = st.sampled_from(("auto", "escrow", "advisory", "skip"))
_RECOMMENDED = st.sampled_from(("auto", "escrow", "advisory", "skip", "needs_data"))
_RULE = st.from_regex(r"[A-Z][A-Z0-9]{1,6}", fullmatch=True)


def _stats(rule: str, current_mode: str, recommended_mode: str) -> RuleStats:
    return RuleStats(
        rule=rule,
        mutation_class="other",
        current_mode=cast("Mode", current_mode),
        prs_with_candidate=1,
        prs_helped=1,
        median_changed_lines=0.0,
        p95_changed_lines=0.0,
        median_outside_diff_lines=0.0,
        p95_outside_diff_lines=0.0,
        unsafe_seen=False,
        revert_signal=0,
        on_pareto_frontier=False,
        recommended_mode=cast("Mode | str", recommended_mode),
        rationale="",
    )


@given(
    rows=st.lists(
        st.tuples(_RULE, _MODE, _RECOMMENDED),
        max_size=20,
    )
)
def test_group_rule_stats_places_each_rule_in_its_bucket(
    rows: list[tuple[str, str, str]],
) -> None:
    rule_stats = tuple(_stats(rule, current, recommended) for rule, current, recommended in rows)

    groups = _group_rule_stats(rule_stats)

    assert set(groups) == {"PROMOTE", "DEMOTE", "KEEP", "NEEDS DATA"}
    assert sum(len(bucket) for bucket in groups.values()) == len(rule_stats)
    assert {
        stat.rule for label, bucket in groups.items() for stat in bucket if _bucket(stat) == label
    } == {stat.rule for stat in rule_stats}


@given(
    rows=st.lists(
        st.tuples(_RULE, _MODE, _RECOMMENDED),
        max_size=20,
    )
)
def test_group_rule_stats_sorts_each_bucket_by_replay_priority(
    rows: list[tuple[str, str, str]],
) -> None:
    rule_stats = tuple(_stats(rule, current, recommended) for rule, current, recommended in rows)

    groups = _group_rule_stats(rule_stats)

    for bucket in groups.values():
        assert bucket == sorted(bucket, key=_rule_sort_key)


@given(
    base=_RULE,
    budget=_RULE,
    requested=st.integers(min_value=0, max_value=50),
    points=st.lists(
        st.tuples(
            st.from_regex(r"[a-f0-9]{7,12}", fullmatch=True),
            st.from_regex(r"[a-f0-9]{7,12}", fullmatch=True),
            st.one_of(st.none(), st.text(min_size=1, max_size=40)),
            st.one_of(st.none(), st.from_regex(r"[a-f0-9]{7,12}", fullmatch=True)),
        ),
        max_size=20,
    ),
    rows=st.lists(st.tuples(_RULE, _MODE, _RECOMMENDED), max_size=20),
)
def test_serialize_preserves_replay_counts_and_rule_order(
    base: str,
    budget: str,
    requested: int,
    points: list[tuple[str, str, str | None, str | None]],
    rows: list[tuple[str, str, str]],
) -> None:
    replay_points = tuple(
        ReplayPoint(commit, parent, (), error, reverted)
        for commit, parent, error, reverted in points
    )
    rule_stats = tuple(_stats(rule, current, recommended) for rule, current, recommended in rows)
    result = ReplayResult(base, budget, requested, replay_points)

    payload = _serialize(result, rule_stats)

    assert payload["base_branch"] == base
    assert payload["budget"] == budget
    assert payload["n_requested"] == requested
    assert payload["n_replayed"] == len(points)
    errors = sum(1 for _commit, _parent, error, _reverted in points if error)
    assert payload["n_with_error"] == errors
    assert [commit["commit"] for commit in payload["commits"]] == [
        commit for commit, _parent, _error, _reverted in points
    ]
    assert [rule["rule"] for rule in payload["rules"]] == [
        stat.rule for stat in sorted(rule_stats, key=_rule_sort_key)
    ]


@given(
    points=st.lists(
        st.tuples(
            st.from_regex(r"[a-f0-9]{7,12}", fullmatch=True),
            st.from_regex(r"[a-f0-9]{7,12}", fullmatch=True),
            st.one_of(st.none(), st.text(min_size=1, max_size=40)),
            st.one_of(st.none(), st.from_regex(r"[a-f0-9]{7,12}", fullmatch=True)),
        ),
        max_size=20,
    )
)
def test_serialize_preserves_each_replay_point_shape(
    points: list[tuple[str, str, str | None, str | None]],
) -> None:
    replay_points = tuple(
        ReplayPoint(commit, parent, (), error, reverted)
        for commit, parent, error, reverted in points
    )

    payload = _serialize(ReplayResult("main", "unblock", len(points), replay_points), ())

    assert payload["commits"] == [
        {
            "commit": commit,
            "parent": parent,
            "samples": [],
            "error": error,
            "reverted_in": reverted,
        }
        for commit, parent, error, reverted in points
    ]


def test_serialize_preserves_empty_replay_shape() -> None:
    payload = _serialize(ReplayResult("main", "unblock", 0, ()), ())

    assert payload["base_branch"] == "main"
    assert payload["budget"] == "unblock"
    assert payload["n_requested"] == 0
    assert payload["n_replayed"] == 0
    assert payload["n_with_error"] == 0
    assert payload["commits"] == []
    assert payload["rules"] == []


@given(
    payload=st.fixed_dictionaries({
        "base_branch": _RULE,
        "budget": _RULE,
        "n_requested": st.integers(min_value=0, max_value=50),
        "n_replayed": st.integers(min_value=0, max_value=50),
        "n_with_error": st.integers(min_value=0, max_value=50),
        "rules": st.lists(
            st.fixed_dictionaries({
                "rule": _RULE,
                "on_pareto_frontier": st.booleans(),
            }),
            max_size=20,
        ),
    })
)
def test_fix_replay_payload_reports_rule_count_and_frontier(
    payload: dict[str, object],
) -> None:
    rules = cast("list[object]", payload["rules"])
    result = _fix_replay_payload(payload, ".lintfix/replay.json")

    assert result["command"] == "fix replay"
    assert result["passed"] is True
    assert result["replay_path"] == ".lintfix/replay.json"
    assert result["rules_count"] == len(rules)
    assert result["pareto_frontier"] == _pareto_frontier(rules)


@given(
    rules=st.one_of(
        st.none(),
        st.text(max_size=40),
        st.dictionaries(st.text(max_size=10), st.text(max_size=10), max_size=5),
        st.lists(st.one_of(st.none(), st.text(max_size=20)), max_size=20),
    ),
    replay_path=st.text(min_size=1, max_size=50),
)
def test_fix_replay_payload_treats_only_list_rules_as_rows(
    rules: object,
    replay_path: str,
) -> None:
    result = _fix_replay_payload({"rules": rules}, replay_path)

    assert result["command"] == "fix replay"
    assert result["passed"] is True
    assert result["status"] == "replayed"
    assert result["replay_path"] == replay_path
    assert result["rules_count"] == (len(rules) if isinstance(rules, list) else 0)


@given(
    rows=st.lists(
        st.one_of(
            st.fixed_dictionaries({
                "rule": _RULE,
                "on_pareto_frontier": st.booleans(),
            }),
            st.text(max_size=20),
            st.none(),
        ),
        max_size=20,
    )
)
def test_pareto_frontier_ignores_non_rows_and_falsy_markers(rows: list[object]) -> None:
    frontier = _pareto_frontier(rows)

    assert frontier == sorted(
        str(row["rule"]) for row in rows if isinstance(row, dict) and row.get("on_pareto_frontier")
    )


@given(marker=st.one_of(st.integers(min_value=1), st.text(min_size=1, max_size=20)))
def test_pareto_frontier_accepts_truthy_frontier_markers(marker: object) -> None:
    assert _pareto_frontier([{"rule": None, "on_pareto_frontier": marker}]) == ["None"]
