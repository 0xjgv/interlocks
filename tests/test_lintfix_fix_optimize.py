"""Integration tests for ``interlocks fix-optimize``.

Builds a real git repo with I001 (import sort) and F401 (unused import)
diagnostics, runs the CLI, and asserts (1) non-mutating by default,
(2) ``.lintfix/optimize.json`` is written with selected/not-selected entries,
(3) ``--apply`` mutates only on clean verify and restores on verify failure.
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
