from __future__ import annotations

import textwrap
from pathlib import Path

from interlocks.behavior_coverage import _parse_feature_behaviors


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_blank_line_between_marker_and_scenario_resets_pending_ids(tmp_path: Path) -> None:
    feature = _write(
        tmp_path / "checkout.feature",
        """
        Feature: checkout

          # req: cli-config

          Scenario: config prints settings
            Given a project
        """,
    )

    parsed = _parse_feature_behaviors(feature)

    assert parsed.scenario_count == 1
    assert parsed.scenario_behaviors == ()


def test_marker_above_background_does_not_bind_to_next_scenario(tmp_path: Path) -> None:
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

    parsed = _parse_feature_behaviors(feature)

    assert parsed.scenario_count == 1
    assert parsed.scenario_behaviors == ()


def test_req_substring_inside_step_line_does_not_bind_to_next_scenario(tmp_path: Path) -> None:
    feature = _write(
        tmp_path / "checkout.feature",
        """
        Feature: checkout

          Scenario: first
            Given a step that mentions # req: bogus literally

          Scenario: second
            Given another step
        """,
    )

    parsed = _parse_feature_behaviors(feature)

    assert parsed.scenario_count == 2
    assert parsed.scenario_behaviors == ()


def test_req_tag_inside_step_line_does_not_bind_to_next_scenario(tmp_path: Path) -> None:
    feature = _write(
        tmp_path / "checkout.feature",
        """
        Feature: checkout

          Scenario: first
            Given a step tagged @req-bogus inline

          Scenario: second
            Given another step
        """,
    )

    parsed = _parse_feature_behaviors(feature)

    assert parsed.scenario_count == 2
    assert parsed.scenario_behaviors == ()
