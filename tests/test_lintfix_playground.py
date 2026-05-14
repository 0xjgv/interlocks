"""Tests for the local lint-fix optimizer playground generator."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType


def _load_script() -> ModuleType:
    script_path = Path(__file__).resolve().parents[1] / "tools" / "create_lintfix_playground.py"
    spec = importlib.util.spec_from_file_location("create_lintfix_playground", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _target(root: Path) -> Path:
    return root / ".factory" / "playgrounds" / "lintfix-optimizer"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _env_with_repo_pythonpath() -> dict[str, str]:
    env = os.environ.copy()
    repo_root = str(Path(__file__).resolve().parents[1])
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{existing}" if existing else repo_root
    return env


def test_create_playground_initializes_dirty_nested_repo(tmp_path: Path) -> None:
    module = _load_script()
    playground = module.create_playground(_target(tmp_path), repo_root=tmp_path)

    assert playground == _target(tmp_path).resolve()
    assert (playground / ".git").is_dir()
    assert (playground / "pyproject.toml").is_file()
    assert (playground / "src" / "playground" / "imports.py").is_file()
    assert (playground / "tests" / "test_smoke.py").is_file()

    commits = _git(playground, "rev-list", "--count", "HEAD")
    assert commits.returncode == 0, commits.stderr
    assert commits.stdout.strip() == "1"

    status = _git(playground, "status", "--short")
    assert status.returncode == 0, status.stderr
    assert "src/playground/imports.py" in status.stdout
    assert "src/playground/newline.py" in status.stdout


def test_create_playground_rejects_unexpected_target(tmp_path: Path) -> None:
    module = _load_script()
    try:
        module.create_playground(tmp_path / "not-the-playground", repo_root=tmp_path)
    except ValueError as exc:
        assert "refusing to recreate unexpected target" in str(exc)
    else:
        raise AssertionError("expected unexpected target to be rejected")


def test_generated_playground_exercises_fix_optimize(tmp_path: Path) -> None:
    module = _load_script()
    playground = module.create_playground(_target(tmp_path), repo_root=tmp_path)

    result = subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "fix-optimize", "--base=HEAD"],
        cwd=playground,
        env=_env_with_repo_pythonpath(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads((playground / ".lintfix" / "optimize.json").read_text(encoding="utf-8"))

    selected_rules = {entry["rule"] for entry in payload["selected"]}
    rejected = {entry["rule"]: entry["reason"] for entry in payload["not_selected"]}

    assert {"I001", "W292"}.issubset(selected_rules)
    assert "F401" in rejected
    assert rejected["F401"] == "policy mode is escrow"
    assert "UP045" in rejected
    assert rejected["UP045"] == "policy mode is escrow"
