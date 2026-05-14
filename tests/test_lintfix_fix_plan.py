"""Tests for ``interlocks fix-plan``.

Two layers:

1. Real-git integration tests with multiple fixable diagnostics (I001 import
   sort + F401 unused import) run through the CLI subprocess: the working tree
   stays clean while ``.lintfix/plan.json`` and the F401 escrow patch are
   materialized.
2. In-process unit tests for ``_print_plan`` — called directly with
   constructed candidate lists, asserting on captured stdout.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from interlocks.lintfix import plan as plan_module
from interlocks.lintfix.budgets import CandidateCost
from interlocks.lintfix.classify import CandidateMetrics, Classification
from interlocks.lintfix.rules import Mode
from interlocks.tasks import fix_plan as fix_plan_mod

_PYPROJECT = textwrap.dedent("""
    [project]
    name = "sample"
    version = "0.0.0"
    requires-python = ">=3.11"

    [tool.ruff]
    target-version = "py311"
    line-length = 99

    [tool.ruff.lint]
    select = ["F", "I"]
""")

_CLEAN_BASE = "import os\nimport sys\n\nprint(sys.version)\nprint(os.name)\n"
# Reorder imports (I001) AND add unused import (F401).
_DIRTY = "import sys\nimport os\nimport json\n\nprint(sys.version)\nprint(os.name)\n"


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git("init", "-q", "-b", "main", cwd=tmp_path)
    _git("config", "user.email", "test@example.com", cwd=tmp_path)
    _git("config", "user.name", "Test", cwd=tmp_path)
    _git("config", "commit.gpgsign", "false", cwd=tmp_path)
    _git("config", "core.hooksPath", "/dev/null", cwd=tmp_path)
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    (tmp_path / "sample.py").write_text(_CLEAN_BASE, encoding="utf-8")
    _git("add", "-A", cwd=tmp_path)
    _git("commit", "-q", "-m", "base", cwd=tmp_path)
    return tmp_path


def _run_fix_plan(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "fix-plan", "--base=HEAD", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_fix_plan_does_not_mutate_tree(repo: Path) -> None:
    f = repo / "sample.py"
    f.write_text(_DIRTY, encoding="utf-8")

    result = _run_fix_plan(repo)

    assert result.returncode == 0, result.stderr + result.stdout
    assert f.read_text(encoding="utf-8") == _DIRTY


def test_fix_plan_writes_json_with_spec_schema(repo: Path) -> None:
    (repo / "sample.py").write_text(_DIRTY, encoding="utf-8")

    result = _run_fix_plan(repo)
    assert result.returncode == 0, result.stderr + result.stdout

    plan_path = repo / ".lintfix" / "plan.json"
    assert plan_path.is_file()
    payload = json.loads(plan_path.read_text(encoding="utf-8"))

    assert payload["base"] == "HEAD"
    assert payload["mode"] == "unblock"
    assert payload["ruff_version"]
    assert isinstance(payload["candidates"], list)

    by_rule = {c["rule"]: c for c in payload["candidates"]}
    assert "I001" in by_rule
    assert "F401" in by_rule
    # I001 is policy auto and the change is tiny — should classify auto.
    assert by_rule["I001"]["classification"] == "auto"
    # F401 is policy escrow regardless of budget.
    assert by_rule["F401"]["classification"] == "escrow"


def test_fix_plan_materializes_escrow_for_non_auto_rules(repo: Path) -> None:
    (repo / "sample.py").write_text(_DIRTY, encoding="utf-8")

    result = _run_fix_plan(repo)
    assert result.returncode == 0, result.stderr + result.stdout

    f401_patch = repo / ".lintfix" / "escrow" / "F401.patch"
    assert f401_patch.is_file()
    assert "import json" in f401_patch.read_text(encoding="utf-8")
    # Auto-eligible candidates are NOT pre-materialized in plan mode.
    assert not (repo / ".lintfix" / "escrow" / "I001.patch").is_file()


def test_fix_plan_exits_clean_when_no_changed_files(repo: Path) -> None:
    # Tree matches HEAD — no diff vs base, no candidates.
    result = _run_fix_plan(repo)
    assert result.returncode == 0, result.stderr + result.stdout
    plan_path = repo / ".lintfix" / "plan.json"
    assert plan_path.is_file()
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    assert payload["candidates"] == []


# ─────────────── in-process unit layer ────────────────────────────


def _planned_candidate(
    *,
    rule: str,
    mode: Mode,
    reason: str | None = None,
    files: tuple[str, ...] = ("sample.py",),
) -> plan_module.PlannedCandidate:
    metrics = CandidateMetrics(
        files_touched=files,
        changed_lines_total=4,
        changed_lines_inside_diff=3,
        changed_lines_outside_diff=1,
        comment_deletes=0,
        control_flow_edits=0,
    )
    classification = Classification(
        rule=rule,
        mode=mode,
        metrics=metrics,
        cost=CandidateCost(
            files_touched=len(files),
            changed_lines_total=4,
            changed_lines_outside_diff=1,
            risk=3,
        ),
        reason=reason,
        patch_id=":".join((rule, *files)),
    )
    return plan_module.PlannedCandidate(
        classification=classification,
        diff_text="DIFF",
        unsafe=False,
        diagnostic_count=1,
        mutation_class="import_sort",
    )


def _plan(*candidates: plan_module.PlannedCandidate) -> plan_module.Plan:
    return plan_module.Plan(
        base="HEAD",
        head="abc123",
        budget="unblock",
        ruff_version="0.x",
        candidates=candidates,
        discovery_error=None,
    )


@pytest.fixture
def verbose(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "fix-plan", "--verbose"])


def test_print_plan_no_candidates(verbose: None, capsys: pytest.CaptureFixture[str]) -> None:
    fix_plan_mod._print_plan(_plan(), "HEAD", "unblock", ".lintfix/plan.json")
    out = capsys.readouterr().out
    assert "(no candidates)" in out
    assert ".lintfix/plan.json" in out


def test_print_plan_single_group(verbose: None, capsys: pytest.CaptureFixture[str]) -> None:
    plan = _plan(_planned_candidate(rule="I001", mode="auto"))
    fix_plan_mod._print_plan(plan, "HEAD", "unblock", "plan.json")
    out = capsys.readouterr().out
    assert "AUTO-APPLY ELIGIBLE" in out
    assert "I001" in out
    # Groups with no members are not printed.
    assert "PATCH ESCROW" not in out
    assert "SKIPPED" not in out


def test_print_plan_all_groups(verbose: None, capsys: pytest.CaptureFixture[str]) -> None:
    plan = _plan(
        _planned_candidate(rule="I001", mode="auto"),
        _planned_candidate(rule="F401", mode="escrow"),
        _planned_candidate(rule="SIM102", mode="advisory", reason="style only"),
        _planned_candidate(rule="UP007", mode="skip", reason="unsafe"),
    )
    fix_plan_mod._print_plan(plan, "HEAD", "unblock", "plan.json")
    out = capsys.readouterr().out
    assert "AUTO-APPLY ELIGIBLE" in out
    assert "PATCH ESCROW" in out
    assert "ADVISORY" in out
    assert "SKIPPED" in out
    # The classifier reason is surfaced in the per-candidate summary line.
    assert "style only" in out
