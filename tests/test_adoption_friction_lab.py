"""Tests for the local adoption-friction lab."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tools import adoption_friction_lib, run_adoption_friction_lab


def test_bare_repo_fixture_uses_local_pyproject_and_dirty_patch(tmp_path: Path) -> None:
    root = tmp_path / "adoption"
    repo = adoption_friction_lib.create_bare_repo(root / "bare-repo", root=root)

    assert (repo / "pyproject.toml").is_file()
    assert "[tool.interlocks]" not in (repo / "pyproject.toml").read_text(encoding="utf-8")

    status = adoption_friction_lib.git(repo, "status", "--short").stdout
    assert "app.py" in status


def test_progressive_fixture_seeds_ratchet_files(tmp_path: Path) -> None:
    root = tmp_path / "adoption"
    repo = adoption_friction_lib.create_progressive_repo(root / "progressive", root=root)

    pyproject = (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert 'preset = "progressive"' in pyproject
    assert (repo / ".interlocks" / "baseline.json").is_file()
    assert (repo / ".interlocks" / "run-summary.json").is_file()


def test_strict_fixture_starts_without_integrations(tmp_path: Path) -> None:
    root = tmp_path / "adoption"
    repo = adoption_friction_lib.create_strict_repo(root / "strict", root=root)

    assert 'preset = "strict"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert not (repo / ".github" / "workflows" / "interlocks.yml").exists()
    assert not (repo / ".git" / "hooks" / "pre-commit").exists()


def test_isolated_env_uses_temp_home_cache_and_repo_pythonpath(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    env = adoption_friction_lib.isolated_env(repo, repo_root=Path("/repo/root"))

    assert env["HOME"] == str(repo / ".lab-home")
    assert env["XDG_CACHE_HOME"] == str(repo / ".lab-cache")
    assert env["UV_CACHE_DIR"] == str(repo / ".lab-uv-cache")
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_CONFIG_SYSTEM"] == os.devnull
    assert env["PYTHONPATH"].startswith("/repo/root")


def test_scenario_run_scores_failed_command_and_missing_fragment(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    run = run_adoption_friction_lab.ScenarioRun("demo", tmp_path)

    result = run.command("definitely-not-a-command")
    assert result.returncode != 0
    assert run.friction_score == 2

    try:
        run.require_fragment(result, "fragment-that-is-not-present")
    except run_adoption_friction_lab.LabFailure:
        pass
    else:
        raise AssertionError("missing fragment should fail")
    assert run.friction_score == 3


def test_write_report_contains_scenario_payload(tmp_path: Path) -> None:
    result = run_adoption_friction_lab.ScenarioResult(
        name="demo",
        passed=True,
        friction_score=2,
        commands=[{"command": "interlocks doctor", "returncode": 0, "elapsed_seconds": 0.1}],
        artifacts=[".interlocks/baseline.json"],
        next_actions=["Run `interlocks setup`"],
        detail="ok",
    )

    path = run_adoption_friction_lab.write_report(tmp_path, [result])
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["scenarios"][0]["name"] == "demo"
    assert payload["scenarios"][0]["friction_score"] == 2
    assert payload["scenarios"][0]["artifacts"] == [".interlocks/baseline.json"]


def test_runner_subprocess_smoke_bare_repo(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "tools" / "run_adoption_friction_lab.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--scenario=bare-repo",
            f"--target-root={tmp_path / 'adoption'}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "[ok] bare-repo" in result.stdout
    assert (tmp_path / "adoption" / "report.json").is_file()
