"""Property tests for behavior coverage parsing and validation."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given
from hypothesis import strategies as st

from interlocks.behavior_coverage import (
    Behavior,
    FeatureBehaviorParse,
    ScenarioBehavior,
    _duplicate_behavior_ids,
    _marker_ids,
    _parse_feature_behaviors,
    behavior_coverage_for_parsed_features,
    format_behavior_coverage_failure,
    parse_feature_behaviors,
    traceable_totals_for_parsed_features,
    validate_behavior_coverage,
)
from interlocks.config import InterlockConfig

_ID = st.from_regex(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,20}", fullmatch=True)
_TITLE = st.from_regex(r"[A-Za-z0-9 _.-]{1,40}", fullmatch=True).filter(str.strip)


def _parse_body(body: str):
    with TemporaryDirectory() as raw_root:
        feature = Path(raw_root) / "generated.feature"
        feature.write_text(body, encoding="utf-8")
        return _parse_feature_behaviors(feature)


@given(ids=st.lists(_ID, min_size=1, max_size=8))
def test_marker_ids_extracts_comment_ids_in_first_seen_order(ids: list[str]) -> None:
    assert _marker_ids("# req: " + " ".join(ids)) == tuple(dict.fromkeys(ids))


@given(ids=st.lists(_ID, min_size=1, max_size=8))
def test_marker_ids_extracts_tag_ids_in_first_seen_order(ids: list[str]) -> None:
    assert _marker_ids(" ".join(f"@req-{behavior_id}" for behavior_id in ids)) == (
        tuple(dict.fromkeys(ids))
    )


@given(first=_ID, second=_ID)
def test_marker_ids_deduplicates_mixed_comment_and_tag_markers(first: str, second: str) -> None:
    expected = tuple(dict.fromkeys([first, second]))

    assert _marker_ids(f"# req: {first} @req-{second} @req-{first}") == expected


@given(behavior_id=_ID, title=_TITLE)
def test_behavior_marker_on_own_line_binds_to_next_scenario(behavior_id: str, title: str) -> None:
    body = f"Feature: generated\n  # req: {behavior_id}\n  Scenario: {title}\n"

    parsed = _parse_body(body)

    assert parsed.scenario_count == 1
    [scenario] = parsed.scenario_behaviors
    assert scenario.behavior_id == behavior_id
    assert scenario.scenario_title == title.strip()
    assert scenario.scenario_line == 3


@given(behavior_id=_ID, title=_TITLE)
def test_inline_req_text_in_step_does_not_bind_to_following_scenario(
    behavior_id: str, title: str
) -> None:
    body = (
        "Feature: generated\n"
        "  Scenario: first\n"
        f"    Given a literal # req: {behavior_id} in step text\n"
        f"  Scenario: {title}\n"
    )

    parsed = _parse_body(body)

    assert parsed.scenario_count == 2
    assert parsed.scenario_behaviors == ()


@given(behavior_id=_ID, title=_TITLE)
def test_inline_req_tag_in_step_does_not_bind_to_following_scenario(
    behavior_id: str, title: str
) -> None:
    body = (
        "Feature: generated\n"
        "  Scenario: first\n"
        f"    Given a literal @req-{behavior_id} in step text\n"
        f"  Scenario: {title}\n"
    )

    parsed = _parse_body(body)

    assert parsed.scenario_count == 2
    assert parsed.scenario_behaviors == ()


@given(rows=st.lists(st.tuples(_ID, _TITLE), max_size=8))
def test_parse_feature_behaviors_aggregates_files_in_sorted_order(
    rows: list[tuple[str, str]],
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        files: list[Path] = []
        expected: list[ScenarioBehavior] = []
        for index, (behavior_id, title) in enumerate(rows):
            path = root / f"{len(rows) - index:02d}.feature"
            path.write_text(
                f"Feature: generated\n  # req: {behavior_id}\n  Scenario: {title}\n",
                encoding="utf-8",
            )
            files.append(path)
            expected.append(ScenarioBehavior(behavior_id, path, title.strip(), 3))

        parsed = parse_feature_behaviors(reversed(files))

    assert parsed.scenario_count == len(rows)
    assert parsed.scenario_behaviors == tuple(sorted(expected))


@given(
    live_ids=st.lists(_ID, max_size=8, unique=True),
    scenario_ids=st.lists(_ID, max_size=8),
)
def test_validate_behavior_coverage_sets_are_generated_differences(
    live_ids: list[str], scenario_ids: list[str]
) -> None:
    behaviors = tuple(Behavior(behavior_id, "task", behavior_id) for behavior_id in live_ids)
    scenarios = tuple(
        ScenarioBehavior(behavior_id, Path("generated.feature"), "generated", index + 1)
        for index, behavior_id in enumerate(scenario_ids)
    )

    result = validate_behavior_coverage(behaviors, scenarios)

    assert result.uncovered_behavior_ids == tuple(sorted(set(live_ids) - set(scenario_ids)))
    expected_stale = [
        scenario for scenario in sorted(scenarios) if scenario.behavior_id not in set(live_ids)
    ]
    assert list(result.stale_scenario_behaviors) == expected_stale


@given(ids=st.lists(_ID, max_size=12))
def test_duplicate_behavior_ids_are_sorted_ids_with_multiple_entries(ids: list[str]) -> None:
    behaviors = tuple(Behavior(behavior_id, "task", behavior_id) for behavior_id in ids)

    duplicates = _duplicate_behavior_ids(behaviors)

    assert duplicates == tuple(
        sorted({behavior_id for behavior_id in ids if ids.count(behavior_id) > 1})
    )


@given(
    scenario_rows=st.lists(
        st.tuples(_ID, _TITLE, st.integers(min_value=1, max_value=1_000)),
        max_size=20,
    ),
    scenario_count=st.integers(min_value=0, max_value=40),
)
def test_traceable_totals_for_parsed_features_counts_unique_marked_scenarios(
    scenario_rows: list[tuple[str, str, int]],
    scenario_count: int,
) -> None:
    scenarios = tuple(
        ScenarioBehavior(behavior_id, Path("generated.feature"), title, line)
        for behavior_id, title, line in scenario_rows
    )
    parsed = FeatureBehaviorParse(scenario_count, scenarios)

    total, traceable = traceable_totals_for_parsed_features(parsed)

    assert total == scenario_count
    assert traceable == len({
        (scenario.feature_path, scenario.scenario_line, scenario.scenario_title)
        for scenario in scenarios
    })


@given(scenario_ids=st.lists(_ID, max_size=10))
def test_behavior_coverage_for_parsed_features_is_complete_without_project_registry(
    scenario_ids: list[str],
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        (root / "pyproject.toml").write_text(
            "[project]\nname = 'other'\n",
            encoding="utf-8",
        )
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "interlocks",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
        )
        parsed = FeatureBehaviorParse(
            scenario_count=len(scenario_ids),
            scenario_behaviors=tuple(
                ScenarioBehavior(behavior_id, Path("generated.feature"), "generated", index + 1)
                for index, behavior_id in enumerate(scenario_ids)
            ),
        )

        result = behavior_coverage_for_parsed_features(cfg, parsed)

    assert result.is_complete
    assert result.coverage.behaviors == ()


@given(behavior_id=_ID)
def test_format_behavior_coverage_failure_mentions_each_gap(behavior_id: str) -> None:
    result = validate_behavior_coverage((Behavior(behavior_id, "task", "summary"),), ())
    message = format_behavior_coverage_failure(result)

    assert "behavior coverage incomplete" in message
    assert f"uncovered behavior ID: {behavior_id}" in message
