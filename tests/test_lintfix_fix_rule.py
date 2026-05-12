"""Integration tests for ``interlocks fix-rule``.

Builds a real git repo, commits a base, introduces a fixable diff, then
exercises plan/escrow/apply paths through the CLI surface. ruff runs for real
under ``uvx``; the verifier is stubbed via ``--verify-cmd`` so the test stays
fast and hermetic.
"""

from __future__ import annotations

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
