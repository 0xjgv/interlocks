"""Tests for ``interlocks fix-rule``.

Two layers:

1. Real-git integration tests that commit a base, introduce a fixable diff,
   then exercise plan/escrow/apply paths through the CLI subprocess surface.
   ruff runs for real under ``uvx``; the verifier is stubbed via ``--verify-cmd``.
2. In-process unit tests that call ``cmd_fix_rule`` and its extracted helpers
   directly with the lintfix seams monkeypatched — no subprocess, no ruff.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from interlocks.lintfix import classify as classify_mod
from interlocks.lintfix import diff as diff_mod
from interlocks.lintfix import simulate as simulate_mod
from interlocks.lintfix import verify as verify_mod
from interlocks.lintfix.budgets import CandidateCost
from interlocks.lintfix.classify import CandidateMetrics, Classification
from interlocks.lintfix.rules import Mode
from interlocks.lintfix.simulate import CandidatePatch
from interlocks.lintfix.verify import VerifyResult
from interlocks.tasks import fix_rule as fix_rule_mod

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
# Reorder to trigger I001 (imports no longer sorted).
_I001_MUTATION = "import sys\nimport os\n\nprint(sys.version)\nprint(os.name)\n"
# Add an unused import to trigger F401.
_F401_MUTATION = "import os\nimport sys\nimport json\n\nprint(sys.version)\nprint(os.name)\n"


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_git(root: Path) -> None:
    _git("init", "-q", "-b", "main", cwd=root)
    _git("config", "user.email", "test@example.com", cwd=root)
    _git("config", "user.name", "Test", cwd=root)
    _git("config", "commit.gpgsign", "false", cwd=root)
    _git("config", "core.hooksPath", "/dev/null", cwd=root)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _init_git(tmp_path)
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    (tmp_path / "sample.py").write_text(_CLEAN_BASE, encoding="utf-8")
    _git("add", "-A", cwd=tmp_path)
    _git("commit", "-q", "-m", "base", cwd=tmp_path)
    return tmp_path


def _run_fix_rule(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "fix-rule", "--base=HEAD", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_plan_mode_does_not_mutate_tree(repo: Path) -> None:
    f = repo / "sample.py"
    f.write_text(_I001_MUTATION, encoding="utf-8")
    result = _run_fix_rule(repo, "--rule=I001")

    assert result.returncode == 0, result.stderr + result.stdout
    # Plan mode must NOT have applied the fix.
    assert f.read_text(encoding="utf-8") == _I001_MUTATION


def test_f401_defaults_to_escrow_and_writes_patch(repo: Path) -> None:
    f = repo / "sample.py"
    f.write_text(_F401_MUTATION, encoding="utf-8")
    result = _run_fix_rule(repo, "--rule=F401", "--apply")

    assert result.returncode == 0, result.stderr + result.stdout
    # F401 is escrow even with --apply.
    assert "import json" in f.read_text(encoding="utf-8")
    escrow = repo / ".lintfix" / "escrow" / "F401.patch"
    assert escrow.is_file()
    assert "import json" in escrow.read_text(encoding="utf-8")


def test_apply_mode_mutates_on_clean_verify(repo: Path) -> None:
    f = repo / "sample.py"
    f.write_text(_I001_MUTATION, encoding="utf-8")
    result = _run_fix_rule(
        repo, "--rule=I001", "--apply", f"--verify-cmd={sys.executable} -c pass"
    )

    assert result.returncode == 0, result.stderr + result.stdout
    fixed = f.read_text(encoding="utf-8")
    # ruff sorted imports back to alphabetical order.
    assert fixed.index("import os") < fixed.index("import sys")


def test_apply_mode_restores_tree_on_verify_failure(repo: Path) -> None:
    f = repo / "sample.py"
    original = _I001_MUTATION
    f.write_text(original, encoding="utf-8")
    result = _run_fix_rule(
        repo,
        "--rule=I001",
        "--apply",
        f'--verify-cmd={sys.executable} -c "import sys;sys.exit(1)"',
    )

    assert result.returncode != 0
    assert f.read_text(encoding="utf-8") == original
    assert (repo / ".lintfix" / "failed.patch").is_file()


def test_no_changed_files_exits_clean(repo: Path) -> None:
    # Tree matches HEAD — no diff vs base.
    result = _run_fix_rule(repo, "--rule=I001")
    assert result.returncode == 0


# ─────────────── in-process unit layer ────────────────────────────


class _FakeCfg:
    """Minimal stand-in for ``InterlockConfig`` — just what fix-rule touches."""

    def __init__(self, root: Path) -> None:
        self.project_root = root

    def relpath(self, path: Path) -> str:
        return str(path.relative_to(self.project_root))


def _metrics(files: tuple[str, ...] = ("sample.py",)) -> CandidateMetrics:
    return CandidateMetrics(
        files_touched=files,
        changed_lines_total=2,
        changed_lines_inside_diff=2,
        changed_lines_outside_diff=0,
        comment_deletes=0,
        control_flow_edits=0,
    )


def _classification(
    *,
    rule: str = "I001",
    mode: Mode = "auto",
    reason: str | None = None,
    files: tuple[str, ...] = ("sample.py",),
) -> Classification:
    return Classification(
        rule=rule,
        mode=mode,
        metrics=_metrics(files),
        cost=CandidateCost(
            files_touched=len(files),
            changed_lines_total=2,
            changed_lines_outside_diff=0,
            risk=2,
        ),
        reason=reason,
        patch_id=":".join((rule, *files)),
    )


def _args(**overrides: object) -> fix_rule_mod._FixRuleArgs:
    base = {
        "rule": "I001",
        "apply": False,
        "base": "origin/main",
        "budget_name": "unblock",
        "verify_cmd": ("interlocks", "ci"),
    }
    base.update(overrides)
    return fix_rule_mod._FixRuleArgs(**base)  # type: ignore[arg-type]


def test_resolve_args_prefers_explicit_kwargs() -> None:
    resolved = fix_rule_mod._resolve_args("F401", True, "main", "renovation", ("echo", "hi"))
    assert resolved == fix_rule_mod._FixRuleArgs(
        rule="F401",
        apply=True,
        base="main",
        budget_name="renovation",
        verify_cmd=("echo", "hi"),
    )


def test_resolve_args_falls_back_to_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["interlocks", "fix-rule", "--rule=I001", "--apply", "--base=dev"],
    )
    resolved = fix_rule_mod._resolve_args(None, None, None, None, None)
    assert resolved.rule == "I001"
    assert resolved.apply is True
    assert resolved.base == "dev"
    assert resolved.budget_name == "unblock"  # argv default
    assert resolved.verify_cmd == ("interlocks", "ci")


def test_dispatch_skip_mode_writes_nothing(tmp_path: Path) -> None:
    cfg = _FakeCfg(tmp_path)
    rc = fix_rule_mod._dispatch_classification(
        _classification(mode="skip", reason="skip by policy"),
        _args(),
        CandidatePatch("I001", ("sample.py",), "", 0),
        ("sample.py",),
        cfg,  # type: ignore[arg-type]
    )
    assert rc == 0
    assert not (tmp_path / ".lintfix").exists()


@pytest.mark.parametrize("mode", ["escrow", "advisory"])
def test_dispatch_escrow_modes_materialize_patch(tmp_path: Path, mode: Mode) -> None:
    cfg = _FakeCfg(tmp_path)
    rc = fix_rule_mod._dispatch_classification(
        _classification(rule="F401", mode=mode),
        _args(rule="F401"),
        CandidatePatch("F401", ("sample.py",), "PATCH-TEXT", 0),
        ("sample.py",),
        cfg,  # type: ignore[arg-type]
    )
    assert rc == 0
    patch = tmp_path / ".lintfix" / "escrow" / "F401.patch"
    assert patch.read_text(encoding="utf-8") == "PATCH-TEXT"


def test_dispatch_auto_without_apply_is_noop(tmp_path: Path) -> None:
    rc = fix_rule_mod._dispatch_classification(
        _classification(mode="auto"),
        _args(apply=False),
        CandidatePatch("I001", ("sample.py",), "diff", 0),
        ("sample.py",),
        _FakeCfg(tmp_path),  # type: ignore[arg-type]
    )
    assert rc == 0
    assert not (tmp_path / ".lintfix").exists()


def test_dispatch_auto_apply_verified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def _fake_apply(*, rule: str, files: tuple[str, ...], verify_cmd: object) -> VerifyResult:
        seen["rule"] = rule
        seen["files"] = files
        return VerifyResult(True, 0, "", "", restored=False)

    monkeypatch.setattr(verify_mod, "apply_with_verify", _fake_apply)
    rc = fix_rule_mod._dispatch_classification(
        _classification(mode="auto"),
        _args(apply=True),
        CandidatePatch("I001", ("sample.py",), "diff", 0),
        ("sample.py",),
        _FakeCfg(tmp_path),  # type: ignore[arg-type]
    )
    assert rc == 0
    assert seen == {"rule": "I001", "files": ("sample.py",)}
    assert not (tmp_path / ".lintfix" / "failed.patch").exists()


def test_dispatch_auto_apply_verify_failure_writes_failed_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        verify_mod,
        "apply_with_verify",
        lambda **_kw: VerifyResult(False, 7, "", "boom", restored=True),
    )
    rc = fix_rule_mod._dispatch_classification(
        _classification(mode="auto"),
        _args(apply=True),
        CandidatePatch("I001", ("sample.py",), "FAILED-DIFF", 0),
        ("sample.py",),
        _FakeCfg(tmp_path),  # type: ignore[arg-type]
    )
    assert rc == 7
    failed = tmp_path / ".lintfix" / "failed.patch"
    assert failed.read_text(encoding="utf-8") == "FAILED-DIFF"


def test_dispatch_auto_apply_falls_back_to_changed_files_when_metrics_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty ``files_touched`` falls back to the caller's changed-file set."""
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        verify_mod,
        "apply_with_verify",
        lambda **kw: captured.update(kw) or VerifyResult(True, 0, "", "", restored=False),
    )
    fix_rule_mod._dispatch_classification(
        _classification(mode="auto", files=()),
        _args(apply=True),
        CandidatePatch("I001", ("a.py", "b.py"), "diff", 0),
        ("a.py", "b.py"),
        _FakeCfg(tmp_path),  # type: ignore[arg-type]
    )
    assert captured["files"] == ("a.py", "b.py")


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Minimal project (pyproject + chdir) so ``load_config`` resolves here."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.0.0"\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_cmd_fix_rule_unknown_base_returns_clean(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(diff_mod, "resolve_base", lambda _base: "")
    # No exception, no exit — just a warn row.
    fix_rule_mod.cmd_fix_rule(rule="I001", base="nope")


def test_cmd_fix_rule_no_changed_files_returns_clean(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(diff_mod, "resolve_base", lambda _base: "basesha")
    monkeypatch.setattr(diff_mod, "changed_files", lambda _base: ())
    fix_rule_mod.cmd_fix_rule(rule="I001")


def test_cmd_fix_rule_ruff_failure_exits_with_rc(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(diff_mod, "resolve_base", lambda _base: "basesha")
    monkeypatch.setattr(diff_mod, "changed_files", lambda _base: ("sample.py",))
    monkeypatch.setattr(
        simulate_mod,
        "simulate_rule",
        lambda _rule, _files: CandidatePatch("I001", ("sample.py",), "", 2),
    )
    with pytest.raises(SystemExit) as exc:
        fix_rule_mod.cmd_fix_rule(rule="I001")
    assert exc.value.code == 2


def test_cmd_fix_rule_auto_plan_path(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(diff_mod, "resolve_base", lambda _base: "basesha")
    monkeypatch.setattr(diff_mod, "changed_files", lambda _base: ("sample.py",))
    monkeypatch.setattr(diff_mod, "changed_hunks", lambda _base, _files: {})
    monkeypatch.setattr(
        simulate_mod,
        "simulate_rule",
        lambda _rule, _files: CandidatePatch("I001", ("sample.py",), "diff", 0),
    )
    monkeypatch.setattr(classify_mod, "classify", lambda **_kw: _classification(mode="auto"))
    # apply=False → no SystemExit, escrow untouched.
    fix_rule_mod.cmd_fix_rule(rule="I001", apply=False)
    assert not (project / ".lintfix").exists()


def test_cmd_fix_rule_escrow_path_writes_patch(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(diff_mod, "resolve_base", lambda _base: "basesha")
    monkeypatch.setattr(diff_mod, "changed_files", lambda _base: ("sample.py",))
    monkeypatch.setattr(diff_mod, "changed_hunks", lambda _base, _files: {})
    monkeypatch.setattr(
        simulate_mod,
        "simulate_rule",
        lambda _rule, _files: CandidatePatch("F401", ("sample.py",), "ESCROW-DIFF", 0),
    )
    monkeypatch.setattr(
        classify_mod,
        "classify",
        lambda **_kw: _classification(rule="F401", mode="escrow"),
    )
    fix_rule_mod.cmd_fix_rule(rule="F401")
    patch = project / ".lintfix" / "escrow" / "F401.patch"
    assert patch.read_text(encoding="utf-8") == "ESCROW-DIFF"
