"""Tests for interlocks.run_summary — accumulator + JSON flush."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from interlocks import run_summary
from interlocks.config import load_config


@pytest.fixture(autouse=True)
def _reset_summary() -> None:
    run_summary.reset()


@pytest.fixture
def tmp_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "p"\nversion = "0"\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_record_and_flush_writes_all_four_numbers(tmp_project: Path) -> None:
    run_summary.record_coverage(82.5)
    run_summary.record_mutation(67.0)
    run_summary.record_crap_max(19.0)
    run_summary.record_attribution_coverage(0.91)
    run_summary.record_context("local")

    cfg = load_config()
    target = run_summary.flush(cfg)

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["coverage_pct"] == 82.5
    assert payload["mutation_score"] == 67.0
    assert payload["crap_max_observed"] == 19.0
    assert payload["attribution_coverage"] == 0.91
    assert payload["context"] == "local"
    assert payload["schema_version"] == 1
    assert isinstance(payload["created_at"], (int, float))


def test_flush_pulls_coverage_from_coverage_json(tmp_project: Path) -> None:
    """When coverage.py wrote .interlocks/coverage.json, flush picks it up."""
    interlocks_dir = tmp_project / ".interlocks"
    interlocks_dir.mkdir()
    (interlocks_dir / "coverage.json").write_text(
        json.dumps({"totals": {"percent_covered": 73.4}}), encoding="utf-8"
    )
    cfg = load_config()
    target = run_summary.flush(cfg)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["coverage_pct"] == 73.4


def test_flush_with_no_recorded_values_writes_empty_summary(tmp_project: Path) -> None:
    cfg = load_config()
    target = run_summary.flush(cfg)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["coverage_pct"] is None
    assert payload["mutation_score"] is None
    assert payload["crap_max_observed"] is None
    assert payload["attribution_coverage"] is None


def test_load_round_trip(tmp_project: Path) -> None:
    run_summary.record_mutation(55.0)
    cfg = load_config()
    run_summary.flush(cfg)
    loaded = run_summary.load(cfg)
    assert loaded is not None
    assert loaded.mutation_score == 55.0


def test_load_returns_none_when_file_missing(tmp_project: Path) -> None:
    cfg = load_config()
    assert run_summary.load(cfg) is None
