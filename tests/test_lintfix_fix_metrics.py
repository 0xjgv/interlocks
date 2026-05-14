"""Unit + integration tests for ``interlocks fix-metrics``."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from interlocks.tasks import fix_metrics


def test_mean_handles_empty_input() -> None:
    assert fix_metrics._mean([]) == 0.0
    assert fix_metrics._mean([5]) == 5.0
    assert fix_metrics._mean([1, 2, 3, 4]) == 2.5


def test_summarize_plan_groups_classifications() -> None:
    plan = {
        "base": "main",
        "head": "abc",
        "candidates": [
            {
                "rule": "I001",
                "classification": "auto",
                "changed_lines_total": 5,
                "changed_lines_outside_diff": 1,
            },
            {
                "rule": "W292",
                "classification": "auto",
                "changed_lines_total": 1,
                "changed_lines_outside_diff": 0,
            },
            {
                "rule": "F401",
                "classification": "escrow",
                "changed_lines_total": 2,
                "changed_lines_outside_diff": 0,
            },
            {
                "rule": "SIM102",
                "classification": "advisory",
                "changed_lines_total": 30,
                "changed_lines_outside_diff": 20,
            },
            {
                "rule": "UP007",
                "classification": "skip",
                "changed_lines_total": 0,
                "changed_lines_outside_diff": 0,
            },
        ],
    }
    summary = fix_metrics._summarize_plan(plan)
    assert summary["candidates_total"] == 5
    assert summary["by_classification"] == {
        "auto": 2,
        "escrow": 1,
        "advisory": 1,
        "skip": 1,
    }
    assert summary["auto_rules"] == ["I001", "W292"]
    assert summary["escrow_rules"] == ["F401"]
    assert summary["advisory_rules"] == ["SIM102"]
    assert summary["skipped_rules"] == ["UP007"]
    assert summary["avg_outside_diff_lines"] == 4.2  # (1+0+0+20+0)/5
    assert summary["avg_changed_lines"] == 7.6  # (5+1+2+30+0)/5


def test_summarize_optimize_counts_rejection_reasons() -> None:
    optimize = {
        "budget": "unblock",
        "total_value": 8,
        "total_cost": {"outside_diff": 0, "changed_lines": 1, "files": 1, "risk": 0},
        "selected": [{"rule": "I001"}],
        "not_selected": [
            {"rule": "F401", "reason": "policy mode is escrow"},
            {"rule": "UP007", "reason": "policy mode is escrow"},
            {"rule": "SIM102", "reason": "would exceed outside-diff budget"},
        ],
    }
    summary = fix_metrics._summarize_optimize(optimize)
    assert summary["selected"] == 1
    assert summary["selected_rules"] == ["I001"]
    assert summary["rejected"] == 3
    assert summary["rejection_reasons"]["policy mode is escrow"] == 2
    assert summary["rejection_reasons"]["would exceed outside-diff budget"] == 1


def test_summarize_replay_lists_pareto_and_recommendations() -> None:
    replay = {
        "n_replayed": 25,
        "n_with_error": 1,
        "rules": [
            {"rule": "I001", "recommended_mode": "auto", "on_pareto_frontier": True},
            {"rule": "W292", "recommended_mode": "auto", "on_pareto_frontier": True},
            {"rule": "F401", "recommended_mode": "escrow", "on_pareto_frontier": False},
        ],
    }
    summary = fix_metrics._summarize_replay(replay)
    assert summary["n_replayed"] == 25
    assert summary["n_with_error"] == 1
    assert summary["rules_total"] == 3
    assert summary["by_recommendation"] == {"auto": 2, "escrow": 1}
    assert summary["pareto_frontier"] == ["I001", "W292"]


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    (tmp_path / ".lintfix").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_missing_all_inputs_writes_empty_metrics(project: Path) -> None:
    fix_metrics.cmd_fix_metrics()
    metrics_path = project / ".lintfix" / "metrics.json"
    assert metrics_path.is_file()
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert payload["sources"] == {"plan": False, "optimize": False, "replay": False}
    assert "plan" not in payload
    assert "optimize" not in payload
    assert "replay" not in payload


def test_plan_only_produces_plan_section(project: Path) -> None:
    plan = {
        "base": "main",
        "head": "abc",
        "candidates": [
            {
                "rule": "I001",
                "classification": "auto",
                "changed_lines_total": 5,
                "changed_lines_outside_diff": 1,
            }
        ],
    }
    (project / ".lintfix" / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    fix_metrics.cmd_fix_metrics()
    payload = json.loads((project / ".lintfix" / "metrics.json").read_text(encoding="utf-8"))
    assert payload["sources"]["plan"] is True
    assert payload["sources"]["optimize"] is False
    assert payload["plan"]["candidates_total"] == 1


@pytest.mark.parametrize("entry", ["cmd", "aggregate"])
def test_aggregate_metrics_and_cmd_wrapper_share_behavior(project: Path, entry: str) -> None:
    """`aggregate_metrics` is the single core; `cmd_fix_metrics` is a thin wrapper."""
    plan = {
        "base": "main",
        "head": "abc",
        "candidates": [
            {
                "rule": "I001",
                "classification": "auto",
                "changed_lines_total": 5,
                "changed_lines_outside_diff": 1,
            }
        ],
    }
    (project / ".lintfix" / "plan.json").write_text(json.dumps(plan), encoding="utf-8")

    if entry == "cmd":
        fix_metrics.cmd_fix_metrics()
    else:
        out_path = fix_metrics.aggregate_metrics(project)
        assert out_path == project / ".lintfix" / "metrics.json"

    payload = json.loads((project / ".lintfix" / "metrics.json").read_text(encoding="utf-8"))
    assert payload["sources"]["plan"] is True
    assert payload["plan"]["candidates_total"] == 1


def test_cli_entrypoint_writes_metrics(project: Path) -> None:
    (project / ".lintfix" / "plan.json").write_text(
        json.dumps({"base": "main", "head": "abc", "candidates": []}),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "fix-metrics"],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert (project / ".lintfix" / "metrics.json").is_file()
