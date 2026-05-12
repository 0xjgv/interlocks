"""Unit + integration tests for ``interlocks fix-annotate``."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from interlocks.tasks import fix_annotate


def _plan_candidate(
    rule: str,
    classification: str,
    files: list[str],
    *,
    outside: int = 0,
    lines: int = 1,
    risk: int = 0,
    patch_path: str | None = None,
) -> dict[str, object]:
    return {
        "id": f"{rule}:{':'.join(files)}",
        "rule": rule,
        "mode": classification,
        "classification": classification,
        "mutation_class": "import_sort",
        "files_touched": len(files),
        "files": files,
        "changed_lines_total": lines,
        "changed_lines_inside_diff": lines,
        "changed_lines_outside_diff": outside,
        "risk": risk,
        "diagnostic_count": 1,
        "unsafe": False,
        "patch_path": patch_path,
        "reason": None,
    }


def test_annotations_emit_one_line_per_file() -> None:
    cand = _plan_candidate("I001", "auto", ["a.py", "b.py"])
    anns = list(fix_annotate._annotations_for(cand))
    assert len(anns) == 2
    assert all(ann.severity == "notice" for ann in anns)
    assert anns[0].line.startswith("::notice file=a.py,line=1::")
    assert anns[1].line.startswith("::notice file=b.py,line=1::")
    assert "[I001]" in anns[0].line


def test_annotations_skip_class_emits_nothing() -> None:
    cand = _plan_candidate("SIM102", "skip", ["a.py"])
    assert list(fix_annotate._annotations_for(cand)) == []


def test_advisory_class_uses_warning_severity() -> None:
    cand = _plan_candidate("C401", "advisory", ["a.py"], outside=20)
    [ann] = list(fix_annotate._annotations_for(cand))
    assert ann.severity == "warning"
    assert ann.line.startswith("::warning file=a.py,line=1::")


def test_escrow_message_cites_patch_path() -> None:
    cand = _plan_candidate(
        "F401",
        "escrow",
        ["api/views.py"],
        patch_path=".lintfix/escrow/F401.patch",
    )
    [ann] = list(fix_annotate._annotations_for(cand))
    assert ".lintfix/escrow/F401.patch" in ann.line


def test_no_files_field_falls_back_to_workflow_level_annotation() -> None:
    cand = _plan_candidate("I001", "auto", [])
    cand["files"] = []
    [ann] = list(fix_annotate._annotations_for(cand))
    assert ann.line.startswith("::notice::")
    assert "file=" not in ann.line


def test_flatten_optimize_pulls_cost_fields_onto_flat_keys() -> None:
    opt_cand = {
        "rule": "I001",
        "policy_mode": "auto",
        "cost": {"outside_diff": 4, "changed_lines": 12, "files": 2, "risk": 3},
        "files": ["a.py", "b.py"],
        "patch_path": None,
    }
    flat = fix_annotate._flatten_optimize(opt_cand)
    assert flat["classification"] == "auto"
    assert flat["files_touched"] == 2
    assert flat["changed_lines_total"] == 12
    assert flat["changed_lines_outside_diff"] == 4
    assert flat["risk"] == 3
    [ann] = list(fix_annotate._annotations_for(flat))[:1]
    assert "12 lines, 4 outside-diff, risk=3" in ann.line


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Minimal project layout with pyproject + .lintfix/."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    (tmp_path / ".lintfix").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _capsys_stdout(capsys: pytest.CaptureFixture[str]) -> str:
    return capsys.readouterr().out


def test_missing_plan_file_exits_zero_with_no_annotations(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with mock.patch.object(sys, "argv", ["interlocks", "fix-annotate"]):
        fix_annotate.cmd_fix_annotate()
    out = _capsys_stdout(capsys)
    assert "::notice" not in out
    assert "::warning" not in out


def test_plan_json_emits_annotations_for_each_candidate(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = {
        "base": "main",
        "head": "abc123",
        "mode": "unblock",
        "ruff_version": "0.x",
        "candidates": [
            _plan_candidate("I001", "auto", ["a.py"]),
            _plan_candidate(
                "F401",
                "escrow",
                ["b.py"],
                patch_path=".lintfix/escrow/F401.patch",
            ),
            _plan_candidate("SIM102", "advisory", ["c.py"], outside=42),
            _plan_candidate("UP007", "skip", ["d.py"]),
        ],
    }
    (project / ".lintfix" / "plan.json").write_text(json.dumps(plan), encoding="utf-8")

    with mock.patch.object(sys, "argv", ["interlocks", "fix-annotate"]):
        fix_annotate.cmd_fix_annotate()
    out = _capsys_stdout(capsys)
    assert "::notice file=a.py,line=1::" in out  # I001
    assert "::notice file=b.py,line=1::" in out  # F401
    assert "::warning file=c.py,line=1::" in out  # SIM102
    # skip never annotates
    assert "UP007" not in out


def test_optimize_source_reads_selected_and_not_selected(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    optimize = {
        "base": "main",
        "head": "abc",
        "budget": "unblock",
        "ruff_version": "0.x",
        "total_value": 8,
        "total_cost": {"outside_diff": 0, "changed_lines": 1, "files": 1, "risk": 0},
        "selected": [
            {
                "rule": "I001",
                "value": 8,
                "cost": {"outside_diff": 0, "changed_lines": 1, "files": 1, "risk": 0},
                "policy_mode": "auto",
                "unsafe": False,
                "files": ["a.py"],
                "patch_path": None,
                "reason": None,
                "diagnostic_count": 1,
            }
        ],
        "not_selected": [
            {
                "rule": "F401",
                "value": 0,
                "cost": {"outside_diff": 0, "changed_lines": 0, "files": 0, "risk": 0},
                "policy_mode": "escrow",
                "unsafe": False,
                "files": ["b.py"],
                "patch_path": ".lintfix/escrow/F401.patch",
                "reason": "policy mode is escrow",
                "diagnostic_count": 1,
            }
        ],
    }
    (project / ".lintfix" / "optimize.json").write_text(json.dumps(optimize), encoding="utf-8")

    with mock.patch.object(sys, "argv", ["interlocks", "fix-annotate", "--source=optimize"]):
        fix_annotate.cmd_fix_annotate()
    out = _capsys_stdout(capsys)
    # Selected I001 (auto) → notice
    assert "::notice file=a.py,line=1::" in out
    assert "[I001]" in out
    # Rejected F401 still has policy mode escrow → notice (advisory hint)
    assert "::notice file=b.py,line=1::" in out
    assert ".lintfix/escrow/F401.patch" in out


def test_cli_entrypoint_runs_fix_annotate(project: Path) -> None:
    """Smoke: the subcommand is wired into `interlocks` and exits 0."""
    plan = {
        "base": "main",
        "head": "abc",
        "mode": "unblock",
        "ruff_version": "0.x",
        "candidates": [_plan_candidate("I001", "auto", ["a.py"])],
    }
    (project / ".lintfix" / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "fix-annotate"],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "::notice file=a.py,line=1::" in result.stdout
