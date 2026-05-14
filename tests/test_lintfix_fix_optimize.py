"""Tests for ``interlocks fix-optimize``.

Two layers:

1. Real-git integration tests with I001 (import sort) and F401 (unused import)
   diagnostics, run through the CLI subprocess: non-mutating by default,
   ``.lintfix/optimize.json`` written with selected/not-selected entries,
   ``--apply`` mutates only on clean verify and restores on verify failure.
2. In-process unit tests for ``cmd_fix_optimize`` and the helpers
   ``_apply_selection``, ``_load_stats``, ``_print_summary`` — called directly
   with the plan builder, optimizer, and verifier monkeypatched.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from interlocks.lintfix import plan as plan_module
from interlocks.lintfix import stats as stats_module
from interlocks.lintfix import verify as verify_mod
from interlocks.lintfix.budgets import CandidateCost
from interlocks.lintfix.classify import CandidateMetrics, Classification
from interlocks.lintfix.optimize import (
    Candidate,
    CostVector,
    RejectedCandidate,
    SelectedCandidate,
    Selection,
)
from interlocks.lintfix.rules import Mode
from interlocks.lintfix.verify import BatchVerifyResult
from interlocks.tasks import fix_optimize as fix_optimize_mod

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
# I001 (out-of-order imports) + F401 (unused json import).
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


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "fix-optimize", "--base=HEAD", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_fix_optimize_does_not_mutate_tree_by_default(repo: Path) -> None:
    f = repo / "sample.py"
    f.write_text(_DIRTY, encoding="utf-8")

    result = _run(repo)

    assert result.returncode == 0, result.stderr + result.stdout
    assert f.read_text(encoding="utf-8") == _DIRTY


def test_fix_optimize_writes_optimize_json_with_selected_and_not_selected(repo: Path) -> None:
    (repo / "sample.py").write_text(_DIRTY, encoding="utf-8")

    result = _run(repo)
    assert result.returncode == 0, result.stderr + result.stdout

    out = repo / ".lintfix" / "optimize.json"
    assert out.is_file()
    payload = json.loads(out.read_text(encoding="utf-8"))

    assert payload["base"] == "HEAD"
    assert payload["budget"] == "unblock"
    assert isinstance(payload["selected"], list)
    assert isinstance(payload["not_selected"], list)

    selected_rules = {c["rule"] for c in payload["selected"]}
    rejected_rules = {c["rule"] for c in payload["not_selected"]}

    # I001 is policy auto and fits the unblock budget — must be selected.
    assert "I001" in selected_rules
    # F401 is policy escrow regardless of budget — must NOT be selected.
    assert "F401" in rejected_rules

    # Every rejected entry carries a non-empty reason string.
    for c in payload["not_selected"]:
        assert c["reason"], c


def test_fix_optimize_never_selects_unsafe_in_unblock(repo: Path) -> None:
    (repo / "sample.py").write_text(_DIRTY, encoding="utf-8")
    result = _run(repo)
    assert result.returncode == 0, result.stderr + result.stdout

    payload = json.loads((repo / ".lintfix" / "optimize.json").read_text(encoding="utf-8"))
    for entry in payload["selected"]:
        assert entry["unsafe"] is False


def test_fix_optimize_apply_mutates_on_clean_verify(repo: Path) -> None:
    f = repo / "sample.py"
    f.write_text(_DIRTY, encoding="utf-8")

    result = _run(repo, "--apply", f"--verify-cmd={sys.executable} -c pass")

    assert result.returncode == 0, result.stderr + result.stdout
    fixed = f.read_text(encoding="utf-8")
    # ruff re-sorted imports back to alphabetical.
    assert fixed.index("import os") < fixed.index("import sys")
    # F401 is escrow-only — the unused import should remain in the tree.
    assert "import json" in fixed


def test_fix_optimize_apply_restores_tree_on_verify_failure(repo: Path) -> None:
    f = repo / "sample.py"
    original = _DIRTY
    f.write_text(original, encoding="utf-8")

    result = _run(
        repo,
        "--apply",
        f'--verify-cmd={sys.executable} -c "import sys;sys.exit(1)"',
    )

    assert result.returncode != 0
    assert f.read_text(encoding="utf-8") == original
    # Failed patch is written for review.
    assert (repo / ".lintfix" / "failed.patch").is_file()


def test_fix_optimize_no_changed_files_exits_clean(repo: Path) -> None:
    result = _run(repo)
    assert result.returncode == 0, result.stderr + result.stdout
    out = repo / ".lintfix" / "optimize.json"
    assert out.is_file()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["selected"] == []
    assert payload["not_selected"] == []


# ─────────────── in-process unit layer ────────────────────────────


def _metrics(files: tuple[str, ...] = ("sample.py",)) -> CandidateMetrics:
    return CandidateMetrics(
        files_touched=files,
        changed_lines_total=2,
        changed_lines_inside_diff=2,
        changed_lines_outside_diff=0,
        comment_deletes=0,
        control_flow_edits=0,
    )


def _planned_candidate(
    *,
    rule: str = "I001",
    mode: Mode = "auto",
    files: tuple[str, ...] = ("sample.py",),
    diff_text: str = "DIFF",
    diagnostic_count: int = 1,
) -> plan_module.PlannedCandidate:
    classification = Classification(
        rule=rule,
        mode=mode,
        metrics=_metrics(files),
        cost=CandidateCost(
            files_touched=len(files),
            changed_lines_total=2,
            changed_lines_outside_diff=0,
            risk=2,
        ),
        reason=None,
        patch_id=":".join((rule, *files)),
    )
    return plan_module.PlannedCandidate(
        classification=classification,
        diff_text=diff_text,
        unsafe=False,
        diagnostic_count=diagnostic_count,
        mutation_class="import_sort",
    )


def _plan(
    *,
    candidates: tuple[plan_module.PlannedCandidate, ...] = (),
    discovery_error: plan_module.DiscoveryError | None = None,
) -> plan_module.Plan:
    return plan_module.Plan(
        base="HEAD",
        head="abc123",
        budget="unblock",
        ruff_version="0.x",
        candidates=candidates,
        discovery_error=discovery_error,
    )


def _opt_candidate(rule: str = "I001", value: int = 8) -> Candidate:
    return Candidate(
        rule=rule,
        value=value,
        cost=CostVector(outside_diff=0, changed_lines=2, files=1, risk=2),
        files=("sample.py",),
        selectable=True,
        policy_mode="auto",
    )


def _selection(
    *,
    selected: tuple[Candidate, ...] = (),
    rejected: tuple[Candidate, ...] = (),
) -> Selection:
    return Selection(
        budget_name="unblock",
        selected=tuple(SelectedCandidate(candidate=c) for c in selected),
        rejected=tuple(RejectedCandidate(candidate=c, reason="displaced") for c in rejected),
        total_value=sum(c.value for c in selected),
        total_cost=CostVector(0, 0, 0, 0),
    )


def _stats_row(rule: str = "I001") -> dict[str, object]:
    return {
        "rule": rule,
        "mutation_class": "import_sort",
        "current_mode": "auto",
        "prs_with_candidate": 5,
        "prs_helped": 5,
        "median_changed_lines": 2.0,
        "p95_changed_lines": 3.0,
        "median_outside_diff_lines": 0.0,
        "p95_outside_diff_lines": 1.0,
        "unsafe_seen": False,
        "revert_signal": 0,
        "on_pareto_frontier": True,
        "recommended_mode": "auto",
        "rationale": "ok",
    }


# --- _load_stats ----------------------------------------------------------


def test_load_stats_empty_path_returns_none(tmp_path: Path) -> None:
    assert fix_optimize_mod._load_stats("", tmp_path) is None


def test_load_stats_missing_file_returns_none(tmp_path: Path) -> None:
    assert fix_optimize_mod._load_stats("nope.json", tmp_path) is None


def test_load_stats_happy_path(tmp_path: Path) -> None:
    (tmp_path / "replay.json").write_text(
        json.dumps({"rules": [_stats_row("I001"), _stats_row("F401")]}),
        encoding="utf-8",
    )
    out = fix_optimize_mod._load_stats("replay.json", tmp_path)
    assert out is not None
    assert set(out) == {"I001", "F401"}
    assert isinstance(out["I001"], stats_module.RuleStats)
    assert out["I001"].prs_helped == 5


def test_load_stats_bad_json_returns_none(tmp_path: Path) -> None:
    (tmp_path / "replay.json").write_text("not json {", encoding="utf-8")
    assert fix_optimize_mod._load_stats("replay.json", tmp_path) is None


def test_load_stats_skips_unparseable_row(tmp_path: Path) -> None:
    (tmp_path / "replay.json").write_text(
        json.dumps({"rules": [_stats_row("I001"), {"rule": "BAD"}]}),
        encoding="utf-8",
    )
    out = fix_optimize_mod._load_stats("replay.json", tmp_path)
    assert out is not None
    assert set(out) == {"I001"}


# --- _print_summary -------------------------------------------------------


@pytest.fixture
def verbose(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "fix-optimize", "--verbose"])


def test_print_summary_no_candidates(verbose: None, capsys: pytest.CaptureFixture[str]) -> None:
    fix_optimize_mod._print_summary(
        _plan(), _selection(), "HEAD", "unblock", ".lintfix/optimize.json"
    )
    out = capsys.readouterr().out
    assert "(no candidates)" in out


def test_print_summary_with_selected_and_rejected(
    verbose: None, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = _plan(candidates=(_planned_candidate(rule="I001"), _planned_candidate(rule="F401")))
    selection = _selection(
        selected=(_opt_candidate("I001"),),
        rejected=(_opt_candidate("F401", value=0),),
    )
    fix_optimize_mod._print_summary(plan, selection, "HEAD", "unblock", "out.json")
    out = capsys.readouterr().out
    assert "SELECTED" in out
    assert "NOT SELECTED" in out
    assert "I001" in out
    assert "F401" in out


def test_print_summary_candidates_but_nothing_selected(
    verbose: None, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = _plan(candidates=(_planned_candidate(rule="F401", mode="escrow"),))
    fix_optimize_mod._print_summary(plan, _selection(), "HEAD", "unblock", "out.json")
    out = capsys.readouterr().out
    assert "(none)" in out


# --- _apply_selection -----------------------------------------------------


def test_apply_selection_nothing_to_apply(tmp_path: Path) -> None:
    # Empty selection → no verifier call, no exit.
    fix_optimize_mod._apply_selection(tmp_path, {}, _selection(), ("interlocks", "ci"))


def test_apply_selection_applied_and_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_by_rule = {"I001": _planned_candidate(rule="I001")}
    seen: dict[str, object] = {}

    def _fake_apply(*, rules_and_files: object, verify_cmd: object) -> BatchVerifyResult:
        seen["rules_and_files"] = rules_and_files
        return BatchVerifyResult(
            applied=True,
            returncode=0,
            stdout="",
            stderr="",
            restored=False,
            applied_rules=("I001",),
        )

    monkeypatch.setattr(verify_mod, "apply_many_with_verify", _fake_apply)
    fix_optimize_mod._apply_selection(
        tmp_path,
        plan_by_rule,
        _selection(selected=(_opt_candidate("I001"),)),
        ("interlocks", "ci"),
    )
    assert seen["rules_and_files"] == (("I001", ("sample.py",)),)
    assert not (tmp_path / ".lintfix" / "failed.patch").exists()


def test_apply_selection_verify_failure_writes_failed_patch_and_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_by_rule = {"I001": _planned_candidate(rule="I001", diff_text="FAILED-DIFF")}
    monkeypatch.setattr(
        verify_mod,
        "apply_many_with_verify",
        lambda **_kw: BatchVerifyResult(
            applied=False,
            returncode=5,
            stdout="",
            stderr="boom",
            restored=True,
            applied_rules=(),
        ),
    )
    with pytest.raises(SystemExit) as exc:
        fix_optimize_mod._apply_selection(
            tmp_path,
            plan_by_rule,
            _selection(selected=(_opt_candidate("I001"),)),
            ("interlocks", "ci"),
        )
    assert exc.value.code == 5
    failed = tmp_path / ".lintfix" / "failed.patch"
    assert failed.read_text(encoding="utf-8") == "FAILED-DIFF"


# --- cmd_fix_optimize -----------------------------------------------------


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.0.0"\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_cmd_fix_optimize_writes_optimize_json(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        plan_module,
        "build_plan",
        lambda **_kw: _plan(candidates=(_planned_candidate(rule="I001"),)),
    )
    monkeypatch.setattr(plan_module, "materialize_escrow_patches", lambda *_a: {})

    fix_optimize_mod.cmd_fix_optimize(
        base="HEAD", budget="unblock", apply=False, stats_path="", verify_cmd=("true",)
    )

    payload = json.loads((project / ".lintfix" / "optimize.json").read_text(encoding="utf-8"))
    assert {c["rule"] for c in payload["selected"]} == {"I001"}


def test_cmd_fix_optimize_discovery_error_exits(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        plan_module,
        "build_plan",
        lambda **_kw: _plan(discovery_error=plan_module.DiscoveryError(2, "ruff boom")),
    )
    with pytest.raises(SystemExit) as exc:
        fix_optimize_mod.cmd_fix_optimize(
            base="HEAD", budget="unblock", apply=False, stats_path="", verify_cmd=("true",)
        )
    assert exc.value.code == 2


def test_cmd_fix_optimize_apply_path_invokes_verifier(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        plan_module,
        "build_plan",
        lambda **_kw: _plan(candidates=(_planned_candidate(rule="I001"),)),
    )
    monkeypatch.setattr(plan_module, "materialize_escrow_patches", lambda *_a: {})
    calls: list[object] = []
    monkeypatch.setattr(
        verify_mod,
        "apply_many_with_verify",
        lambda **kw: (
            calls.append(kw)
            or BatchVerifyResult(
                applied=True,
                returncode=0,
                stdout="",
                stderr="",
                restored=False,
                applied_rules=("I001",),
            )
        ),
    )

    fix_optimize_mod.cmd_fix_optimize(
        base="HEAD", budget="unblock", apply=True, stats_path="", verify_cmd=("true",)
    )
    assert len(calls) == 1
