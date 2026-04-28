from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from interlocks import behavior_coverage as bc
from interlocks.behavior_coverage import (
    Behavior,
    BehaviorRegistry,
    ScenarioBehavior,
    behavior_coverage_for_parsed_features,
    parse_feature_behaviors,
)
from interlocks.config import InterlockConfig, clear_cache, load_config

_OUTLINE_PYPROJECT = '[project]\nname = "probe"\nversion = "0.0.0"\n'

_OUTLINE_FEATURE = """\
Feature: outlines

  # req: task-coverage
  Scenario Outline: coverage threshold accepts <value>
    Given coverage min <value>

    Examples:
      | value |
      | 80    |
      | 90    |
"""

_OUTLINE_FEATURE_NO_MARKER = """\
Feature: outlines

  Scenario Outline: coverage threshold accepts <value>
    Given coverage min <value>

    Examples:
      | value |
      | 80    |
      | 90    |
"""


def _write_feature(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _cfg(project_root: Path) -> InterlockConfig:
    (project_root / "pyproject.toml").write_text(_OUTLINE_PYPROJECT, encoding="utf-8")
    clear_cache()
    return replace(load_config(project_root), project_root=project_root)


@pytest.fixture
def pin_registry(monkeypatch: pytest.MonkeyPatch) -> Callable[[Behavior], None]:
    def pin(*behaviors: Behavior) -> None:
        registry = BehaviorRegistry(behaviors)
        monkeypatch.setattr(bc, "behavior_registry_for_config", lambda _cfg: registry)

    return pin


def test_comment_marker_binds_once_to_scenario_outline(tmp_path: Path) -> None:
    feature = _write_feature(tmp_path / "outline.feature", _OUTLINE_FEATURE)

    parsed = parse_feature_behaviors([feature])

    assert parsed.scenario_behaviors == (
        ScenarioBehavior("task-coverage", feature, "coverage threshold accepts <value>", 4),
    )
    assert parsed.scenario_count == 1


def test_outline_with_marker_passes_validation(
    tmp_path: Path, pin_registry: Callable[..., None]
) -> None:
    pin_registry(Behavior("task-coverage", "task", "coverage"))
    cfg = _cfg(tmp_path)
    feature = _write_feature(tmp_path / "outline.feature", _OUTLINE_FEATURE)

    result = behavior_coverage_for_parsed_features(cfg, parse_feature_behaviors([feature]))

    assert result.is_complete
    assert result.uncovered_behavior_ids == ()
    assert result.coverage.scenario_ids == ("task-coverage",)


def test_outline_without_marker_leaves_live_behavior_uncovered(
    tmp_path: Path, pin_registry: Callable[..., None]
) -> None:
    pin_registry(Behavior("task-coverage", "task", "coverage"))
    cfg = _cfg(tmp_path)
    feature = _write_feature(tmp_path / "outline.feature", _OUTLINE_FEATURE_NO_MARKER)

    result = behavior_coverage_for_parsed_features(cfg, parse_feature_behaviors([feature]))

    assert not result.is_complete
    assert result.uncovered_behavior_ids == ("task-coverage",)
    assert result.coverage.scenario_ids == ()
