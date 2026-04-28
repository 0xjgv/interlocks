from __future__ import annotations

import textwrap
from pathlib import Path

from interlocks.behavior_coverage import (
    INTERLOCKS_REGISTRY,
    Behavior,
    BehaviorRegistry,
    ScenarioBehavior,
    format_behavior_coverage_failure,
    parse_scenario_behaviors,
    validate_behavior_coverage,
)


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_duplicate_behavior_ids_are_invalid() -> None:
    registry = BehaviorRegistry((
        Behavior("task-same", "task", "first"),
        Behavior("task-same", "task", "second"),
    ))

    result = validate_behavior_coverage(registry.behaviors, ())

    assert result.duplicate_behavior_ids == ("task-same",)
    assert not result.is_complete


def test_private_helpers_do_not_require_registry_entries() -> None:
    assert all(
        not behavior.public_symbol.split(":")[-1].startswith("_")
        for behavior in INTERLOCKS_REGISTRY.behaviors
        if behavior.public_symbol
    )


def test_registry_reports_sorted_unique_live_ids() -> None:
    registry = BehaviorRegistry((
        Behavior("task-z", "task", "z"),
        Behavior("task-a", "task", "a"),
        Behavior("task-z", "task", "z again"),
    ))

    assert registry.live_ids == ("task-a", "task-z")


def test_comment_marker_maps_scenario_to_behavior(tmp_path: Path) -> None:
    feature = _write(
        tmp_path / "checkout.feature",
        """
        Feature: checkout

          # req: cli-config
          Scenario: config prints settings
            Given a project
        """,
    )

    assert parse_scenario_behaviors([feature]) == (
        ScenarioBehavior("cli-config", feature, "config prints settings", 5),
    )


def test_tag_marker_maps_scenario_to_behavior(tmp_path: Path) -> None:
    feature = _write(
        tmp_path / "checkout.feature",
        """
        Feature: checkout

          @req-cli-config
          Scenario: config prints settings
            Given a project
        """,
    )

    assert parse_scenario_behaviors([feature]) == (
        ScenarioBehavior("cli-config", feature, "config prints settings", 5),
    )


def test_multiple_markers_are_preserved(tmp_path: Path) -> None:
    feature = _write(
        tmp_path / "checkout.feature",
        """
        Feature: checkout

          # req: cli-config task-coverage
          @req-stage-ci
          Scenario: config prints settings
            Given a project
        """,
    )

    assert parse_scenario_behaviors([feature]) == (
        ScenarioBehavior("cli-config", feature, "config prints settings", 6),
        ScenarioBehavior("stage-ci", feature, "config prints settings", 6),
        ScenarioBehavior("task-coverage", feature, "config prints settings", 6),
    )


def test_unattached_comment_is_ignored(tmp_path: Path) -> None:
    feature = _write(
        tmp_path / "checkout.feature",
        """
        Feature: checkout

          # req: cli-config
          Background:
            Given a project

          Scenario: config prints settings
            Given a project
        """,
    )

    assert parse_scenario_behaviors([feature]) == ()


def test_scenario_outline_and_nested_features_preserve_details(tmp_path: Path) -> None:
    feature = _write(
        tmp_path / "nested" / "checkout.feature",
        """
        Feature: checkout

          @req-task-coverage
          Scenario Outline: coverage threshold
            Given min <value>
        """,
    )

    assert parse_scenario_behaviors([feature]) == (
        ScenarioBehavior("task-coverage", feature, "coverage threshold", 5),
    )


def test_covered_behavior_passes_validation(tmp_path: Path) -> None:
    feature = _write(
        tmp_path / "checkout.feature",
        """
        Feature: checkout

          # req: task-coverage
          Scenario: coverage threshold
            Given coverage
        """,
    )

    result = validate_behavior_coverage(
        (Behavior("task-coverage", "task", "coverage"),),
        parse_scenario_behaviors([feature]),
    )

    assert result.is_complete
    assert result.uncovered_behavior_ids == ()
    assert result.stale_scenario_behaviors == ()


def test_uncovered_behavior_and_stale_marker_fail_validation(tmp_path: Path) -> None:
    feature = _write(
        tmp_path / "checkout.feature",
        """
        Feature: checkout

          # req: task-removed
          Scenario: removed behavior
            Given coverage
        """,
    )

    result = validate_behavior_coverage(
        (Behavior("task-coverage", "task", "coverage"),),
        parse_scenario_behaviors([feature]),
    )

    assert result.uncovered_behavior_ids == ("task-coverage",)
    assert [scenario.behavior_id for scenario in result.stale_scenario_behaviors] == [
        "task-removed"
    ]
    assert "uncovered behavior ID: task-coverage" in format_behavior_coverage_failure(result)
    assert "stale behavior ID: task-removed" in format_behavior_coverage_failure(result)
