from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from interlocks import behavior_coverage as bc
from interlocks.acceptance_status import (
    AcceptanceStatus,
    classify_acceptance_with_details,
    remediation_message,
)
from interlocks.behavior_coverage import (
    Behavior,
    BehaviorRegistry,
    format_behavior_coverage_failure,
    validate_behavior_coverage,
)
from interlocks.config import InterlockConfig, clear_cache, load_config

_DUPLICATE_LINE = "invalid duplicate behavior ID: task-same — keep one live registry entry"


def _cfg(project_root: Path, **overrides: object) -> InterlockConfig:
    (project_root / "pyproject.toml").write_text(
        '[project]\nname = "probe"\nversion = "0.0.0"\n', encoding="utf-8"
    )
    clear_cache()
    return replace(load_config(project_root), project_root=project_root, **overrides)


def test_validate_behavior_coverage_flags_duplicate_registry_entries() -> None:
    registry = BehaviorRegistry((
        Behavior("task-same", "task", "first entry"),
        Behavior("task-same", "task", "second entry"),
    ))

    result = validate_behavior_coverage(registry.behaviors, ())

    assert result.duplicate_behavior_ids == ("task-same",)
    assert not result.is_complete
    assert _DUPLICATE_LINE in format_behavior_coverage_failure(result)


def test_classify_acceptance_with_details_surfaces_duplicate_registry_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    features = tmp_path / "tests" / "features"
    features.mkdir(parents=True)
    (features / "ok.feature").write_text(
        "Feature: ok\n  # req: task-same\n  Scenario: covered\n    Given precondition\n",
        encoding="utf-8",
    )
    duplicate_registry = BehaviorRegistry((
        Behavior("task-same", "task", "first entry"),
        Behavior("task-same", "task", "second entry"),
    ))
    monkeypatch.setattr(bc, "behavior_registry_for_config", lambda _cfg: duplicate_registry)
    cfg = _cfg(tmp_path, features_dir=features, require_acceptance=True)

    classification = classify_acceptance_with_details(cfg)

    assert classification.status is AcceptanceStatus.MISSING_BEHAVIOR_COVERAGE
    assert classification.behavior_result is not None
    assert classification.behavior_result.duplicate_behavior_ids == ("task-same",)
    message = remediation_message(
        classification.status, classification.features_dir, classification.behavior_result
    )
    assert _DUPLICATE_LINE in message
