"""Tests for ``interlocks fix plan``.

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
from typing import cast

import pytest

from interlocks.config import InterlockConfig
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
        [sys.executable, "-m", "interlocks.cli", "fix", "plan", "--base=HEAD", *args],
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


def test_fix_plan_json_reports_plan_summary(repo: Path) -> None:
    (repo / "sample.py").write_text(_DIRTY, encoding="utf-8")

    result = _run_fix_plan(repo, "--json")

    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["command"] == "fix plan"
    assert payload["passed"] is True
    assert payload["status"] == "planned"
    assert payload["base"] == "HEAD"
    assert payload["budget"] == "unblock"
    assert payload["plan_path"] == ".lintfix/plan.json"
    assert payload["candidate_count"] >= 2
    assert payload["by_classification"]["auto"] >= 1
    assert payload["by_classification"]["escrow"] >= 1
    assert (repo / ".lintfix" / "plan.json").is_file()


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
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def verbose(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "fix", "plan", "--verbose"])


def test_print_plan_no_candidates(verbose: None, capsys: pytest.CaptureFixture[str]) -> None:
    fix_plan_mod._print_plan(_plan(), "HEAD", "unblock", ".lintfix/plan.json")
    out = capsys.readouterr().out
    assert "[fix plan]" in out
    assert "0 candidate(s)" in out
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


def test_summary_formats_candidate_metrics_and_reason_exactly() -> None:
    candidate = _planned_candidate(rule="SIM102", mode="advisory", reason="style only")

    assert fix_plan_mod._summary(candidate) == (
        "1 files  4 lines  1 outside-diff  risk=3  style only"
    )


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


def test_print_plan_default_mode_reports_plan_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(fix_plan_mod.ui, "is_verbose", lambda: False)
    plan = _plan(_planned_candidate(rule="I001", mode="auto"))

    fix_plan_mod._print_plan(plan, "HEAD", "unblock", ".lintfix/plan.json")

    out = capsys.readouterr().out
    assert "[fix plan]" in out
    assert ".lintfix/plan.json" in out
    assert "1 candidate(s)" in out


def test_print_plan_status_row_arguments_are_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows: list[tuple[str, str, str, str, str]] = []

    def fake_gate_row(
        command: str,
        target: str,
        status: str,
        *,
        detail: str,
        state: str,
    ) -> None:
        rows.append((command, target, status, detail, state))

    monkeypatch.setattr(fix_plan_mod.ui, "gate_row", fake_gate_row)

    fix_plan_mod._print_plan(_plan(), "BASE", "budget-name", ".lintfix/plan.json")

    assert rows == [
        (
            "fix plan",
            ".lintfix/plan.json",
            "ok",
            "0 candidate(s), base=BASE, budget=budget-name",
            "ok",
        )
    ]


def test_write_plan_artifacts_passes_patch_payload_and_returns_relpath(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = InterlockConfig(
        project_root=tmp_path,
        src_dir=tmp_path / "src",
        test_dir=tmp_path / "tests",
        test_runner="pytest",
        test_invoker="python",
    )
    plan = _plan(_planned_candidate(rule="F401", mode="escrow"))
    patch_paths = {"F401": tmp_path / ".lintfix" / "escrow" / "F401.patch"}
    payload = {"serialized": True, "patches": ["F401.patch"]}
    calls: dict[str, object] = {}

    def fake_materialize_escrow_patches(
        root: Path,
        observed_plan: plan_module.Plan,
    ) -> dict[str, Path]:
        calls["materialize"] = (root, observed_plan)
        return patch_paths

    def fake_serialize(
        observed_plan: plan_module.Plan,
        *,
        patch_paths: dict[str, Path],
    ) -> dict[str, object]:
        calls["serialize"] = (observed_plan, patch_paths)
        return payload

    def fake_write_plan_json(root: Path, observed_payload: dict[str, object]) -> Path:
        calls["write"] = (root, observed_payload)
        return root / ".lintfix" / "plan.json"

    monkeypatch.setattr(
        plan_module,
        "materialize_escrow_patches",
        fake_materialize_escrow_patches,
    )
    monkeypatch.setattr(plan_module, "serialize", fake_serialize)
    monkeypatch.setattr(plan_module, "write_plan_json", fake_write_plan_json)

    assert fix_plan_mod._write_plan_artifacts(cfg, plan) == ".lintfix/plan.json"
    assert calls == {
        "materialize": (tmp_path, plan),
        "serialize": (plan, patch_paths),
        "write": (tmp_path, payload),
    }


def test_render_plan_json_passes_exact_payload_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(_planned_candidate(rule="I001", mode="auto"))
    calls: list[tuple[plan_module.Plan, str, str, str]] = []
    printed: list[dict[str, object]] = []

    def fake_payload(
        observed_plan: plan_module.Plan,
        base: str,
        budget_name: str,
        plan_rel: str,
    ) -> dict[str, object]:
        calls.append((observed_plan, base, budget_name, plan_rel))
        return {"command": "fix plan", "plan_path": plan_rel}

    def fail_print_plan(*_args: object, **_kwargs: object) -> None:
        pytest.fail("_print_plan should not run in JSON mode")

    def fake_print_json(payload: dict[str, object]) -> None:
        printed.append(payload)

    monkeypatch.setattr(fix_plan_mod.ui, "is_json", lambda: True)
    monkeypatch.setattr(fix_plan_mod, "_fix_plan_payload", fake_payload)
    monkeypatch.setattr(fix_plan_mod.ui, "print_json", fake_print_json)
    monkeypatch.setattr(fix_plan_mod, "_print_plan", fail_print_plan)

    fix_plan_mod._render_plan(plan, "BASE", "budget-name", ".lintfix/plan.json")

    assert calls == [(plan, "BASE", "budget-name", ".lintfix/plan.json")]
    assert printed == [{"command": "fix plan", "plan_path": ".lintfix/plan.json"}]


def test_render_plan_human_passes_exact_print_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(_planned_candidate(rule="I001", mode="auto"))
    calls: list[tuple[plan_module.Plan, str, str, str]] = []

    def fake_print_plan(
        observed_plan: plan_module.Plan,
        base: str,
        budget_name: str,
        plan_rel: str,
    ) -> None:
        calls.append((observed_plan, base, budget_name, plan_rel))

    def fail_payload(*_args: object, **_kwargs: object) -> dict[str, object]:
        pytest.fail("_fix_plan_payload should not run in human mode")

    monkeypatch.setattr(fix_plan_mod.ui, "is_json", lambda: False)
    monkeypatch.setattr(fix_plan_mod, "_print_plan", fake_print_plan)
    monkeypatch.setattr(fix_plan_mod, "_fix_plan_payload", fail_payload)

    fix_plan_mod._render_plan(plan, "BASE", "budget-name", ".lintfix/plan.json")

    assert calls == [(plan, "BASE", "budget-name", ".lintfix/plan.json")]


def test_fix_plan_payload_reports_exact_machine_contract() -> None:
    plan = _plan(
        _planned_candidate(rule="I001", mode="auto"),
        _planned_candidate(rule="F401", mode="escrow"),
        _planned_candidate(rule="F841", mode="escrow"),
        _planned_candidate(rule="SIM102", mode="advisory"),
    )

    assert fix_plan_mod._fix_plan_payload(
        plan,
        "BASE",
        "budget-name",
        ".lintfix/plan.json",
    ) == {
        "command": "fix plan",
        "passed": True,
        "status": "planned",
        "base": "BASE",
        "budget": "budget-name",
        "plan_path": ".lintfix/plan.json",
        "candidate_count": 4,
        "by_classification": {
            "auto": 1,
            "escrow": 2,
            "advisory": 1,
            "skip": 0,
        },
        "ruff_version": "0.x",
    }


def test_classification_counts_includes_zeroes_and_runtime_modes() -> None:
    plan = _plan(
        _planned_candidate(rule="I001", mode="auto"),
        _planned_candidate(rule="X001", mode=cast(Mode, "future-mode")),
    )

    assert fix_plan_mod._classification_counts(plan) == {
        "auto": 1,
        "escrow": 0,
        "advisory": 0,
        "skip": 0,
        "future-mode": 1,
    }


def test_cmd_fix_plan_json_in_process_writes_plan(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "fix", "plan", "--json"])
    monkeypatch.setattr(
        plan_module,
        "build_plan",
        lambda **_kw: _plan(_planned_candidate(rule="I001", mode="auto")),
    )

    fix_plan_mod.cmd_fix_plan(base="HEAD", budget="unblock")

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "fix plan"
    assert payload["passed"] is True
    assert payload["candidate_count"] == 1
    assert (project / ".lintfix" / "plan.json").is_file()


def test_cmd_fix_plan_discovery_error_json_exits(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "fix", "plan", "--json"])
    monkeypatch.setattr(
        plan_module,
        "build_plan",
        lambda **_kw: plan_module.Plan(
            base="HEAD",
            head="abc123",
            budget="unblock",
            ruff_version="0.x",
            candidates=(),
            discovery_error=plan_module.DiscoveryError(2, "ruff boom"),
        ),
    )

    with pytest.raises(SystemExit) as exc:
        fix_plan_mod.cmd_fix_plan(base="HEAD", budget="unblock")

    assert exc.value.code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "fix plan"
    assert payload["passed"] is False
    assert payload["status"] == "discovery-failed"
    assert payload["stderr_excerpt"] == "ruff boom"


def test_fix_plan_error_payload_preserves_returncode_and_excerpt() -> None:
    error = plan_module.DiscoveryError(
        7,
        "\nruff failed\n\nfirst diagnostic\n",
    )

    assert fix_plan_mod._fix_plan_error_payload(error) == {
        "command": "fix plan",
        "passed": False,
        "status": "discovery-failed",
        "returncode": 7,
        "stderr_excerpt": "ruff failed\nfirst diagnostic",
    }


def test_fix_plan_error_payload_defaults_without_error_attrs() -> None:
    assert fix_plan_mod._fix_plan_error_payload(object()) == {
        "command": "fix plan",
        "passed": False,
        "status": "discovery-failed",
        "returncode": 1,
        "stderr_excerpt": "",
    }


def test_fix_plan_error_payload_defaults_non_int_returncode() -> None:
    class Error:
        returncode = "2"
        stderr = "ruff failed"

    assert fix_plan_mod._fix_plan_error_payload(Error()) == {
        "command": "fix plan",
        "passed": False,
        "status": "discovery-failed",
        "returncode": 1,
        "stderr_excerpt": "ruff failed",
    }


def test_stderr_excerpt_stringifies_non_string_stderr() -> None:
    assert fix_plan_mod._stderr_excerpt(123) == "123"


def test_stderr_excerpt_limits_nonblank_lines_to_twenty() -> None:
    stderr = "\n".join(f"line {number}" for number in range(1, 22))

    assert fix_plan_mod._stderr_excerpt(stderr) == "\n".join(
        f"line {number}" for number in range(1, 21)
    )
