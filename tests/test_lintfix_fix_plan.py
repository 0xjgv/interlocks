"""Integration tests for ``interlocks fix-plan``.

Builds a real git repo, introduces multiple kinds of fixable diagnostics
(I001 import sort + F401 unused import), runs the CLI, and asserts the
working tree stayed clean while ``.lintfix/plan.json`` and the F401 escrow
patch were both materialized.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

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
