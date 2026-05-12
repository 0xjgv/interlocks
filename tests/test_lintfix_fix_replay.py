"""Tests for ``interlocks fix-replay``.

Two layers:

1. A real-git integration test that builds a small history (a few commits,
   each introducing an ``I001`` import-order finding) and exercises the
   full subprocess pipeline end-to-end.
2. A unit-level test that monkeypatches ``replay_history`` so the CLI's
   aggregation + serialization paths can be checked without running ruff.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from interlocks.lintfix import replay as replay_module
from interlocks.lintfix import stats as stats_module
from interlocks.tasks import fix_replay as fix_replay_module

_PYPROJECT = textwrap.dedent("""
    [project]
    name = "sample"
    version = "0.0.0"
    requires-python = ">=3.11"

    [tool.ruff]
    target-version = "py311"
    line-length = 99

    [tool.ruff.lint]
    select = ["I"]
""")

_CLEAN = "import os\nimport sys\n\nprint(os.name, sys.version)\n"
_REORDERED = "import sys\nimport os\n\nprint(os.name, sys.version)\n"


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo_with_history(tmp_path: Path) -> Path:
    _git("init", "-q", "-b", "main", cwd=tmp_path)
    _git("config", "user.email", "test@example.com", cwd=tmp_path)
    _git("config", "user.name", "Test", cwd=tmp_path)
    _git("config", "commit.gpgsign", "false", cwd=tmp_path)
    _git("config", "core.hooksPath", "/dev/null", cwd=tmp_path)
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    (tmp_path / "a.py").write_text(_CLEAN, encoding="utf-8")
    _git("add", "-A", cwd=tmp_path)
    _git("commit", "-q", "-m", "base", cwd=tmp_path)

    # Commit 2: introduce I001 in a.py.
    (tmp_path / "a.py").write_text(_REORDERED, encoding="utf-8")
    _git("add", "-A", cwd=tmp_path)
    _git("commit", "-q", "-m", "reorder a", cwd=tmp_path)

    # Commit 3: introduce I001 in a new file b.py.
    (tmp_path / "b.py").write_text(_REORDERED, encoding="utf-8")
    _git("add", "-A", cwd=tmp_path)
    _git("commit", "-q", "-m", "add b with reorder", cwd=tmp_path)

    return tmp_path


def _run_fix_replay(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "fix-replay", "--base=main", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_fix_replay_writes_replay_json_with_expected_schema(repo_with_history: Path) -> None:
    result = _run_fix_replay(repo_with_history, "--n=2")
    assert result.returncode == 0, result.stderr + result.stdout

    plan_path = repo_with_history / ".lintfix" / "replay.json"
    assert plan_path.is_file()
    payload = json.loads(plan_path.read_text(encoding="utf-8"))

    assert payload["base_branch"] == "main"
    assert payload["budget"] == "unblock"
    assert payload["n_requested"] == 2
    assert payload["n_replayed"] == 2
    assert isinstance(payload["commits"], list)
    assert isinstance(payload["rules"], list)

    # Each commit dict carries the keys the spec expects.
    for c in payload["commits"]:
        assert set(c.keys()) >= {"commit", "parent", "samples", "error", "reverted_in"}


def test_fix_replay_observes_i001_in_history(repo_with_history: Path) -> None:
    result = _run_fix_replay(repo_with_history, "--n=2")
    assert result.returncode == 0, result.stderr + result.stdout

    payload = json.loads(
        (repo_with_history / ".lintfix" / "replay.json").read_text(encoding="utf-8")
    )
    by_rule = {r["rule"]: r for r in payload["rules"]}
    assert "I001" in by_rule
    assert by_rule["I001"]["prs_with_candidate"] >= 1


def test_fix_replay_does_not_mutate_tree(repo_with_history: Path) -> None:
    """The replay must never leave behind a worktree, a checkout, or a dirty index."""
    before = (repo_with_history / "a.py").read_text(encoding="utf-8")
    _run_fix_replay(repo_with_history, "--n=2")
    after = (repo_with_history / "a.py").read_text(encoding="utf-8")
    assert before == after

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_with_history,
        capture_output=True,
        text=True,
        check=True,
    )
    # Only the generated .lintfix/ directory may show up as untracked.
    dirty = [line for line in status.stdout.splitlines() if not line.endswith(".lintfix/")]
    assert not dirty, status.stdout


def test_cmd_fix_replay_serializes_recommendation_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI's aggregation+serialization path must surface recommendations.

    Drives ``cmd_fix_replay`` with ``replay_history`` swapped for a fixture
    that returns enough synthetic samples to clear the exact-catalog
    observation floor, then asserts ``replay.json`` carries a per-rule
    ``recommended_mode`` and ``on_pareto_frontier`` flag.
    """
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    def _fake_replay(**_kw: object) -> replay_module.ReplayResult:
        samples = tuple(
            stats_module.CandidateSample(
                rule="F401",
                mutation_class="import_delete",
                classification="escrow",
                changed_lines_total=1,
                changed_lines_outside_diff=1,
                risk=6,
                unsafe=False,
                commit=f"c{i}",
                reverted_in=None,
            )
            for i in range(5)
        )
        points = tuple(
            replay_module.ReplayPoint(
                commit=f"c{i}",
                parent=f"p{i}",
                samples=(samples[i],),
                error=None,
                reverted_in=None,
            )
            for i in range(5)
        )
        return replay_module.ReplayResult(
            base_branch="main",
            budget_name="unblock",
            requested=5,
            points=points,
        )

    monkeypatch.setattr(replay_module, "replay_history", _fake_replay)

    fix_replay_module.cmd_fix_replay(base="main", n=5, budget="unblock")

    payload = json.loads((tmp_path / ".lintfix" / "replay.json").read_text(encoding="utf-8"))
    by_rule = {r["rule"]: r for r in payload["rules"]}
    assert "F401" in by_rule
    f401 = by_rule["F401"]
    assert f401["prs_helped"] == 5
    assert f401["on_pareto_frontier"] is True
    # Exact-catalog F401 with low outside-diff promotes from escrow → auto.
    assert f401["recommended_mode"] == "auto"
    assert f401["rationale"]
