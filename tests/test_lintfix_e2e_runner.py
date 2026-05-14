"""Tests for the local lint-fix e2e runner."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tools import run_lintfix_e2e


def test_run_scenarios_stops_after_first_failure(tmp_path: Path) -> None:
    calls: list[str] = []

    def _fail(_context: run_lintfix_e2e.ScenarioContext) -> None:
        calls.append("fail")
        raise run_lintfix_e2e.E2EFailure("boom")

    def _pass(_context: run_lintfix_e2e.ScenarioContext) -> None:
        calls.append("pass")

    original = run_lintfix_e2e.SCENARIOS.copy()
    try:
        run_lintfix_e2e.SCENARIOS.clear()
        run_lintfix_e2e.SCENARIOS.update({"fail": _fail, "pass": _pass})
        context = run_lintfix_e2e.ScenarioContext(
            target_root=tmp_path / "e2e",
            repo_root=Path(__file__).resolve().parents[1],
            verbose=False,
        )

        results = run_lintfix_e2e.run_scenarios(("fail", "pass"), context, keep_going=False)
    finally:
        run_lintfix_e2e.SCENARIOS.clear()
        run_lintfix_e2e.SCENARIOS.update(original)

    assert calls == ["fail"]
    assert len(results) == 1
    assert results[0].passed is False
    assert results[0].detail == "boom"


def test_run_scenarios_keep_going_collects_failures(tmp_path: Path) -> None:
    calls: list[str] = []

    def _fail(_context: run_lintfix_e2e.ScenarioContext) -> None:
        calls.append("fail")
        raise run_lintfix_e2e.E2EFailure("boom")

    def _pass(_context: run_lintfix_e2e.ScenarioContext) -> None:
        calls.append("pass")

    original = run_lintfix_e2e.SCENARIOS.copy()
    try:
        run_lintfix_e2e.SCENARIOS.clear()
        run_lintfix_e2e.SCENARIOS.update({"fail": _fail, "pass": _pass})
        context = run_lintfix_e2e.ScenarioContext(
            target_root=tmp_path / "e2e",
            repo_root=Path(__file__).resolve().parents[1],
            verbose=False,
        )

        results = run_lintfix_e2e.run_scenarios(("fail", "pass"), context, keep_going=True)
    finally:
        run_lintfix_e2e.SCENARIOS.clear()
        run_lintfix_e2e.SCENARIOS.update(original)

    assert calls == ["fail", "pass"]
    assert [result.passed for result in results] == [False, True]


def test_run_cli_captures_interlocks_output(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    result = run_lintfix_e2e.run_cli(
        tmp_path,
        "help",
        repo_root=Path(__file__).resolve().parents[1],
    )

    assert result.returncode == 0
    assert "Usage: interlocks <command>" in result.stdout


def test_runner_subprocess_smoke_fix_optimize_preview(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "tools" / "run_lintfix_e2e.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--scenario=fix-optimize-preview",
            f"--target-root={tmp_path / 'lintfix-e2e'}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "[ok] fix-optimize-preview" in result.stdout


def test_runner_subprocess_smoke_fix_optimize_budget(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "tools" / "run_lintfix_e2e.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--scenario=fix-optimize-budget",
            f"--target-root={tmp_path / 'lintfix-e2e'}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "[ok] fix-optimize-budget" in result.stdout
