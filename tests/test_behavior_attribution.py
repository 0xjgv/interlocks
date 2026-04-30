from __future__ import annotations

import json
import os
import time
from pathlib import Path

from interlocks.behavior_attribution import (
    AttributionEvidence,
    ScenarioReach,
    evidence_is_fresh,
    format_attribution_failure,
    load_evidence,
    validate_attribution,
)
from interlocks.behavior_coverage import Behavior, BehaviorRegistry, ScenarioBehavior
from interlocks.config import InterlockConfig


def _feature(tmp_path: Path, marker: str, title: str = "coverage threshold") -> Path:
    path = tmp_path / "tests" / "features" / "behavior.feature"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"Feature: behavior\n\n  {marker}\n  Scenario: {title}\n    Given a thing\n",
        encoding="utf-8",
    )
    return path


def test_validate_attribution_passes_when_claim_reaches_symbol(tmp_path: Path) -> None:
    feature = _feature(tmp_path, "# req: task-coverage", "coverage threshold")
    scenario = ScenarioBehavior("task-coverage", feature, "coverage threshold", 4)
    registry = BehaviorRegistry((
        Behavior("task-coverage", "task", "coverage", "pkg.mod:covered"),
    ))
    evidence = AttributionEvidence(
        (ScenarioReach(feature, 4, frozenset({"pkg.mod:covered"})),), created_at=time.time()
    )

    result = validate_attribution(registry, (scenario,), evidence)

    assert result.is_complete
    assert result.mis_attributed == ()
    assert result.unresolved_behaviors == ()


def test_validate_attribution_reports_mis_attributed_claim(tmp_path: Path) -> None:
    feature = _feature(tmp_path, "# req: task-coverage", "coverage threshold")
    scenario = ScenarioBehavior("task-coverage", feature, "coverage threshold", 4)
    registry = BehaviorRegistry((
        Behavior("task-coverage", "task", "coverage", "pkg.mod:expected"),
    ))
    evidence = AttributionEvidence(
        (ScenarioReach(feature, 4, frozenset({"pkg.mod:other"})),), created_at=time.time()
    )

    result = validate_attribution(registry, (scenario,), evidence)

    assert not result.is_complete
    assert result.mis_attributed[0].public_symbol == "pkg.mod:expected"
    assert result.unresolved_behaviors[0].behavior_id == "task-coverage"
    assert "mis-attributed" in format_attribution_failure(result)


def test_validate_attribution_reports_instrumentation_gap(tmp_path: Path) -> None:
    feature = _feature(tmp_path, "# req: task-coverage", "coverage threshold")
    scenario = ScenarioBehavior("task-coverage", feature, "coverage threshold", 4)
    registry = BehaviorRegistry((
        Behavior("task-coverage", "task", "coverage", "pkg.mod:expected"),
    ))

    result = validate_attribution(registry, (scenario,), None)

    assert result.instrumentation_gaps
    assert result.unresolved_behaviors
    assert "instrumentation gaps" in format_attribution_failure(result)


def test_load_evidence_returns_none_for_missing_or_malformed_json(tmp_path: Path) -> None:
    assert load_evidence(tmp_path / "missing.json") is None
    path = tmp_path / "bad.json"
    path.write_text("{not-json", encoding="utf-8")

    assert load_evidence(path) is None


def test_load_evidence_parses_valid_records_and_ignores_invalid_items(tmp_path: Path) -> None:
    path = tmp_path / "behavior-attribution.json"
    feature = tmp_path / "x.feature"
    path.write_text(
        json.dumps({
            "created_at": 123.0,
            "failure": "partial failure",
            "scenarios": [
                {
                    "feature_path": str(feature),
                    "scenario_line": 3,
                    "reached_symbols": ["pkg.mod:foo", 123],
                },
                {"feature_path": str(feature), "scenario_line": "bad", "reached_symbols": []},
            ],
        }),
        encoding="utf-8",
    )

    evidence = load_evidence(path)

    assert evidence is not None
    assert evidence.created_at == 123.0
    assert evidence.failure == "partial failure"
    assert evidence.scenarios == (ScenarioReach(feature, 3, frozenset({"pkg.mod:foo"})),)


def test_symbol_less_behavior_is_informational_only(tmp_path: Path) -> None:
    feature = _feature(tmp_path, "# req: task-symbol-less")
    scenario = ScenarioBehavior("task-symbol-less", feature, "coverage threshold", 4)
    registry = BehaviorRegistry((Behavior("task-symbol-less", "task", "no public symbol"),))

    result = validate_attribution(registry, (scenario,), None)

    assert result.is_complete
    assert result.informational_symbol_less[0].behavior_id == "task-symbol-less"
    assert "informational symbol-less behaviors" in format_attribution_failure(result)


def test_aggregate_trace_is_diagnostic_only(tmp_path: Path) -> None:
    feature = _feature(tmp_path, "# req: task-coverage")
    scenario = ScenarioBehavior("task-coverage", feature, "coverage threshold", 4)
    registry = BehaviorRegistry((
        Behavior("task-coverage", "task", "coverage", "pkg.mod:expected"),
    ))

    result = validate_attribution(
        registry,
        (scenario,),
        None,
        aggregate_reached_symbols=("pkg.mod:expected",),
    )

    assert not result.is_complete
    formatted = format_attribution_failure(result)
    assert "aggregate trace fallback" in formatted
    assert "diagnostic only" in formatted


def test_evidence_is_fresh_handles_missing_stale_and_fresh_evidence(tmp_path: Path) -> None:
    features_dir = tmp_path / "tests" / "features"
    feature = _feature(tmp_path, "# req: task-coverage")
    step_def = tmp_path / "tests" / "step_defs" / "test_steps.py"
    step_def.parent.mkdir(parents=True, exist_ok=True)
    step_def.write_text("def step(): pass\n", encoding="utf-8")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname = 'x'\n", encoding="utf-8")
    cfg = InterlockConfig(
        project_root=tmp_path,
        src_dir=tmp_path / "src",
        test_dir=tmp_path / "tests",
        test_runner="pytest",
        test_invoker="python",
        features_dir=features_dir,
    )
    evidence = tmp_path / ".interlocks" / "behavior-attribution.json"

    assert not evidence_is_fresh(cfg, evidence)

    evidence.parent.mkdir()
    evidence.write_text('{"created_at": 1, "failure": null, "scenarios": []}\n', encoding="utf-8")
    old = time.time() - 10
    os.utime(evidence, (old, old))
    now = time.time()
    os.utime(feature, (now, now))

    assert not evidence_is_fresh(cfg, evidence)

    future = time.time() + 10
    os.utime(evidence, (future, future))

    assert evidence_is_fresh(cfg, evidence)
