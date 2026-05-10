"""Tests for the ``interlocks baseline`` CLI subcommand."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from interlocks import run_summary
from interlocks.baseline import BaselineFloor, baseline_path, load_baseline, write_baseline
from interlocks.config import load_config
from interlocks.tasks.baseline_cmd import cmd_baseline


@pytest.fixture(autouse=True)
def _reset_summary() -> None:
    run_summary.reset()


@pytest.fixture
def progressive_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "p"\nversion = "0"\n[tool.interlocks]\npreset = "progressive"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _set_argv(monkeypatch: pytest.MonkeyPatch, args: list[str]) -> None:
    monkeypatch.setattr("sys.argv", ["interlocks", "baseline", *args])


def test_baseline_show_json_with_no_floor(
    progressive_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _set_argv(monkeypatch, ["show", "--json"])
    cmd_baseline()
    payload = json.loads(capsys.readouterr().out)
    assert payload["coverage_min"] is None
    assert payload["mutation_min_score"] is None
    assert payload["path"] == ".interlocks/baseline.json"


def test_baseline_show_json_with_floor(
    progressive_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = load_config()
    write_baseline(
        cfg,
        BaselineFloor(coverage_min=72.0, advanced_from_sha="abc1234"),
    )
    _set_argv(monkeypatch, ["show", "--json"])
    cmd_baseline()
    payload = json.loads(capsys.readouterr().out)
    assert payload["coverage_min"] == 72.0
    assert payload["advanced_from_sha"] == "abc1234"


def test_baseline_advance_writes_new_floor_when_better(
    progressive_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = load_config()
    write_baseline(cfg, BaselineFloor(coverage_min=64.0))
    # Stub a higher run summary on disk.
    (progressive_project / ".interlocks" / "run-summary.json").write_text(
        json.dumps({
            "schema_version": 1,
            "coverage_pct": 70.0,
            "mutation_score": None,
            "crap_max_observed": None,
            "attribution_coverage": None,
            "context": "main_push",
            "created_at": 0,
        }),
        encoding="utf-8",
    )

    _set_argv(monkeypatch, ["advance", "--json"])
    cmd_baseline()

    payload = json.loads(capsys.readouterr().out)
    assert payload["advanced"] is True
    assert payload["coverage_min"] == 70.0
    assert load_baseline(cfg).coverage_min == 70.0


def test_baseline_advance_noop_when_not_better(
    progressive_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = load_config()
    write_baseline(cfg, BaselineFloor(coverage_min=80.0))
    original = baseline_path(cfg).read_bytes()
    (progressive_project / ".interlocks" / "run-summary.json").write_text(
        json.dumps({
            "schema_version": 1,
            "coverage_pct": 70.0,
            "mutation_score": None,
            "crap_max_observed": None,
            "attribution_coverage": None,
            "context": None,
            "created_at": 0,
        }),
        encoding="utf-8",
    )

    _set_argv(monkeypatch, ["advance", "--json"])
    cmd_baseline()

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"advanced": False}
    assert baseline_path(cfg).read_bytes() == original


def test_baseline_init_captures_current_summary(
    progressive_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (progressive_project / ".interlocks").mkdir()
    (progressive_project / ".interlocks" / "run-summary.json").write_text(
        json.dumps({
            "schema_version": 1,
            "coverage_pct": 65.0,
            "mutation_score": 50.0,
            "crap_max_observed": 22.0,
            "attribution_coverage": 0.8,
            "context": None,
            "created_at": 0,
        }),
        encoding="utf-8",
    )

    _set_argv(monkeypatch, ["init", "--json"])
    cmd_baseline()

    cfg = load_config()
    floor = load_baseline(cfg)
    assert floor.coverage_min == 65.0
    assert floor.mutation_min_score == 50.0
    assert floor.crap_max == 22.0
    assert floor.attribution_min_coverage == 0.8


def test_baseline_check_passes_when_at_or_above_floor(
    progressive_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = load_config()
    write_baseline(cfg, BaselineFloor(coverage_min=70.0))
    (progressive_project / ".interlocks" / "run-summary.json").write_text(
        json.dumps({
            "schema_version": 1,
            "coverage_pct": 72.0,
            "mutation_score": None,
            "crap_max_observed": None,
            "attribution_coverage": None,
            "context": None,
            "created_at": 0,
        }),
        encoding="utf-8",
    )

    _set_argv(monkeypatch, ["check", "--json"])
    cmd_baseline()


def test_baseline_check_fails_when_below_floor(
    progressive_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = load_config()
    write_baseline(cfg, BaselineFloor(coverage_min=80.0))
    (progressive_project / ".interlocks" / "run-summary.json").write_text(
        json.dumps({
            "schema_version": 1,
            "coverage_pct": 60.0,
            "mutation_score": None,
            "crap_max_observed": None,
            "attribution_coverage": None,
            "context": None,
            "created_at": 0,
        }),
        encoding="utf-8",
    )

    _set_argv(monkeypatch, ["check", "--json"])
    with pytest.raises(SystemExit) as exc:
        cmd_baseline()
    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert any("below floor" in r for r in payload["regressions"])
