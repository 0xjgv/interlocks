"""Tests for interlocks.baseline — load/write/merge/advance helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from interlocks.baseline import (
    BaselineFloor,
    advance_from_summary,
    floor_from_summary,
    is_strictly_better,
    load_baseline,
    merge_higher,
    write_baseline,
)
from interlocks.config import load_config
from interlocks.run_summary import RunSummary


@pytest.fixture
def progressive_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "p"\nversion = "0"\n[tool.interlocks]\npreset = "progressive"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_baseline_load_missing_file(progressive_project: Path) -> None:
    cfg = load_config()
    floor = load_baseline(cfg)
    assert floor.is_empty
    assert floor.coverage_min is None
    assert floor.mutation_min_score is None


def test_baseline_load_corrupt_file_returns_empty(progressive_project: Path) -> None:
    (progressive_project / ".interlocks").mkdir()
    (progressive_project / ".interlocks" / "baseline.json").write_text(
        "{not json", encoding="utf-8"
    )
    cfg = load_config()
    assert load_baseline(cfg).is_empty


def test_baseline_write_round_trip(progressive_project: Path) -> None:
    cfg = load_config()
    floor = BaselineFloor(
        coverage_min=72.0,
        mutation_min_score=55.0,
        crap_max=22.0,
        attribution_min_coverage=0.9,
        advanced_from_sha="abc1234",
    )
    target = write_baseline(cfg, floor)
    assert target.is_file()
    loaded = load_baseline(cfg)
    assert loaded.coverage_min == 72.0
    assert loaded.mutation_min_score == 55.0
    assert loaded.crap_max == 22.0
    assert loaded.attribution_min_coverage == 0.9
    assert loaded.advanced_from_sha == "abc1234"
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1


def test_baseline_merge_higher_picks_better_per_metric() -> None:
    a = BaselineFloor(coverage_min=70.0, crap_max=30.0, attribution_min_coverage=0.7)
    b = BaselineFloor(coverage_min=65.0, crap_max=20.0, attribution_min_coverage=0.9)
    merged = merge_higher(a, b)
    assert merged.coverage_min == 70.0
    assert merged.crap_max == 20.0
    assert merged.attribution_min_coverage == 0.9


def test_baseline_merge_higher_handles_none_sides() -> None:
    a = BaselineFloor(coverage_min=70.0)
    b = BaselineFloor(crap_max=18.0)
    merged = merge_higher(a, b)
    assert merged.coverage_min == 70.0
    assert merged.crap_max == 18.0


def test_baseline_is_strictly_better_when_one_metric_improves() -> None:
    current = BaselineFloor(coverage_min=70.0, crap_max=30.0)
    candidate = BaselineFloor(coverage_min=72.0, crap_max=30.0)
    assert is_strictly_better(candidate, current)


def test_baseline_is_strictly_better_false_on_regression() -> None:
    current = BaselineFloor(coverage_min=70.0)
    candidate = BaselineFloor(coverage_min=65.0)
    assert not is_strictly_better(candidate, current)


def test_baseline_is_strictly_better_false_when_equal() -> None:
    current = BaselineFloor(coverage_min=70.0, crap_max=30.0)
    candidate = BaselineFloor(coverage_min=70.0, crap_max=30.0)
    assert not is_strictly_better(candidate, current)


def test_baseline_advance_strictly_better_writes_new_floor(progressive_project: Path) -> None:
    cfg = load_config()
    write_baseline(cfg, BaselineFloor(coverage_min=64.0))
    summary = RunSummary(coverage_pct=67.0)
    new_floor = advance_from_summary(cfg, summary, sha="def5678")
    assert new_floor is not None
    assert new_floor.coverage_min == 67.0
    assert new_floor.advanced_from_sha == "def5678"


def test_baseline_advance_returns_none_when_not_better(progressive_project: Path) -> None:
    cfg = load_config()
    write_baseline(cfg, BaselineFloor(coverage_min=70.0))
    summary = RunSummary(coverage_pct=70.0)
    assert advance_from_summary(cfg, summary) is None


def test_baseline_advance_returns_none_for_empty_summary(progressive_project: Path) -> None:
    cfg = load_config()
    assert advance_from_summary(cfg, RunSummary()) is None


def test_floor_from_summary_maps_fields() -> None:
    summary = RunSummary(
        coverage_pct=80.0,
        mutation_score=60.0,
        crap_max_observed=12.0,
        attribution_coverage=0.95,
    )
    floor = floor_from_summary(summary)
    assert floor.coverage_min == 80.0
    assert floor.mutation_min_score == 60.0
    assert floor.crap_max == 12.0
    assert floor.attribution_min_coverage == 0.95
