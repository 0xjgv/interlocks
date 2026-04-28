"""Tests for interlocks.acceptance_status — classifier, counter, remediation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from interlocks.acceptance_status import (
    AcceptanceStatus,
    classify_acceptance,
    count_scenarios,
    feature_files,
    remediation_message,
    required_acceptance_failure_task,
)
from interlocks.config import InterlockConfig, clear_cache, load_config

_MINIMAL_PYPROJECT = '[project]\nname = "probe"\nversion = "0.0.0"\n'


def _cfg(project_root: Path, **overrides: object) -> InterlockConfig:
    """Build an InterlockConfig rooted at ``project_root`` with optional field overrides."""
    (project_root / "pyproject.toml").write_text(_MINIMAL_PYPROJECT, encoding="utf-8")
    clear_cache()
    return replace(load_config(project_root), project_root=project_root, **overrides)


def _write_feature(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# ─────────────── classify_acceptance ─────────────────────


def test_classify_disabled_when_runner_off(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, acceptance_runner="off", features_dir=None)
    assert classify_acceptance(cfg) is AcceptanceStatus.DISABLED


def test_classify_disabled_overrides_require_acceptance(tmp_path: Path) -> None:
    """`off` short-circuits even when require_acceptance=True (explicit opt-out)."""
    cfg = _cfg(
        tmp_path,
        acceptance_runner="off",
        features_dir=None,
        require_acceptance=True,
    )
    assert classify_acceptance(cfg) is AcceptanceStatus.DISABLED


def test_classify_optional_missing_when_no_features_dir(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, features_dir=None, require_acceptance=False)
    assert classify_acceptance(cfg) is AcceptanceStatus.OPTIONAL_MISSING


def test_classify_optional_missing_when_features_dir_empty(tmp_path: Path) -> None:
    features = tmp_path / "tests" / "features"
    features.mkdir(parents=True)
    cfg = _cfg(tmp_path, features_dir=features, require_acceptance=False)
    assert classify_acceptance(cfg) is AcceptanceStatus.OPTIONAL_MISSING


def test_classify_optional_missing_when_features_have_no_scenarios(tmp_path: Path) -> None:
    features = tmp_path / "tests" / "features"
    _write_feature(features / "stub.feature", "Feature: stub\n  # no scenarios yet\n")
    cfg = _cfg(tmp_path, features_dir=features, require_acceptance=False)
    assert classify_acceptance(cfg) is AcceptanceStatus.OPTIONAL_MISSING


def test_classify_missing_features_dir_when_required(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, features_dir=None, require_acceptance=True)
    assert classify_acceptance(cfg) is AcceptanceStatus.MISSING_FEATURES_DIR


def test_classify_missing_feature_files_when_required(tmp_path: Path) -> None:
    features = tmp_path / "tests" / "features"
    features.mkdir(parents=True)
    cfg = _cfg(tmp_path, features_dir=features, require_acceptance=True)
    assert classify_acceptance(cfg) is AcceptanceStatus.MISSING_FEATURE_FILES


def test_classify_missing_scenarios_when_required(tmp_path: Path) -> None:
    features = tmp_path / "tests" / "features"
    _write_feature(features / "shell.feature", "Feature: header only\n")
    cfg = _cfg(tmp_path, features_dir=features, require_acceptance=True)
    assert classify_acceptance(cfg) is AcceptanceStatus.MISSING_SCENARIOS


def test_classify_runnable_with_scenario_when_optional(tmp_path: Path) -> None:
    features = tmp_path / "tests" / "features"
    _write_feature(
        features / "ok.feature",
        "Feature: ok\n  Scenario: a thing happens\n    Given precondition\n",
    )
    cfg = _cfg(tmp_path, features_dir=features, require_acceptance=False)
    assert classify_acceptance(cfg) is AcceptanceStatus.RUNNABLE


def test_classify_runnable_with_scenario_when_required(tmp_path: Path) -> None:
    features = tmp_path / "tests" / "features"
    _write_feature(
        features / "ok.feature",
        "Feature: ok\n  Scenario: a thing happens\n    Given precondition\n",
    )
    cfg = _cfg(tmp_path, features_dir=features, require_acceptance=True)
    assert classify_acceptance(cfg) is AcceptanceStatus.RUNNABLE


def test_classify_missing_behavior_coverage_when_required(tmp_path: Path) -> None:
    features = tmp_path / "tests" / "features"
    _write_feature(
        features / "ok.feature",
        "Feature: ok\n  Scenario: a thing happens\n    Given precondition\n",
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "interlocks"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    clear_cache()
    cfg = replace(
        load_config(tmp_path),
        project_root=tmp_path,
        features_dir=features,
        require_acceptance=True,
    )
    assert classify_acceptance(cfg) is AcceptanceStatus.MISSING_BEHAVIOR_COVERAGE


# ─────────────── feature_files + count_scenarios ─────────────────────


def test_feature_files_returns_empty_for_none(tmp_path: Path) -> None:
    assert feature_files(None) == []


def test_feature_files_returns_empty_for_missing_dir(tmp_path: Path) -> None:
    assert feature_files(tmp_path / "nope") == []


def test_feature_files_collects_recursively(tmp_path: Path) -> None:
    (tmp_path / "a.feature").write_text("", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "b.feature").write_text("", encoding="utf-8")
    paths = feature_files(tmp_path)
    assert {p.name for p in paths} == {"a.feature", "b.feature"}


def test_count_scenarios_empty_iterable_is_zero() -> None:
    assert count_scenarios([]) == 0


def test_count_scenarios_counts_outline_and_scenario(tmp_path: Path) -> None:
    f = tmp_path / "many.feature"
    f.write_text(
        "Feature: many\n"
        "  Scenario: first one\n"
        "    Given a\n"
        "  Scenario Outline: parametric one\n"
        "    Given <x>\n",
        encoding="utf-8",
    )
    assert count_scenarios([f]) == 2


def test_count_scenarios_ignores_comments_and_feature_header(tmp_path: Path) -> None:
    f = tmp_path / "hollow.feature"
    f.write_text(
        "Feature: hollow\n  # Scenario: this is a comment\n  # not real\n",
        encoding="utf-8",
    )
    assert count_scenarios([f]) == 0


# ─────────────── remediation_message ─────────────────────


def test_remediation_for_missing_features_dir_mentions_init() -> None:
    msg = remediation_message(AcceptanceStatus.MISSING_FEATURES_DIR, None)
    assert "interlocks init-acceptance" in msg


def test_remediation_for_missing_feature_files_mentions_dir_and_init(tmp_path: Path) -> None:
    target = tmp_path / "tests" / "features"
    msg = remediation_message(AcceptanceStatus.MISSING_FEATURE_FILES, target)
    assert "init-acceptance" in msg
    assert str(target) in msg


def test_remediation_for_missing_feature_files_uses_default_when_no_dir() -> None:
    msg = remediation_message(AcceptanceStatus.MISSING_FEATURE_FILES, None)
    assert "init-acceptance" in msg
    assert "tests/features" in msg


def test_remediation_for_missing_scenarios_mentions_scenario() -> None:
    msg = remediation_message(AcceptanceStatus.MISSING_SCENARIOS, Path("x"))
    assert "Scenario" in msg


def test_remediation_for_runnable_is_empty() -> None:
    assert remediation_message(AcceptanceStatus.RUNNABLE, None) == ""


def test_remediation_for_disabled_is_empty() -> None:
    assert remediation_message(AcceptanceStatus.DISABLED, None) == ""


def test_remediation_for_optional_missing_is_empty() -> None:
    assert remediation_message(AcceptanceStatus.OPTIONAL_MISSING, None) == ""


def test_required_acceptance_failure_task_exits_with_remediation(tmp_path: Path) -> None:
    task = required_acceptance_failure_task(
        AcceptanceStatus.MISSING_FEATURE_FILES, tmp_path / "features"
    )

    payload = task.cmd[-1]
    assert task.description == "Acceptance (required)"
    assert "no `.feature` files" in payload
    assert "features" in payload
    assert "sys.exit(1)" in payload
