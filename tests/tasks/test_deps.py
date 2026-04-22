"""Integration + unit tests for `harness deps` (deptry dependency hygiene)."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_CLEAN_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "deps-probe"
    version = "0.0.1"
    requires-python = ">=3.13"
    dependencies = []

    [build-system]
    requires = ["setuptools>=61"]
    build-backend = "setuptools.build_meta"
    """
)

_DIRTY_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "deps-probe"
    version = "0.0.1"
    requires-python = ">=3.13"
    dependencies = ["requests>=2"]

    [build-system]
    requires = ["setuptools>=61"]
    build-backend = "setuptools.build_meta"
    """
)

_SRC_INIT = '"""Minimal package."""\n'


@pytest.fixture
def clean_project(tmp_path: Path) -> Path:
    """Package that imports only stdlib — deptry should be happy."""
    (tmp_path / "pyproject.toml").write_text(_CLEAN_PYPROJECT, encoding="utf-8")
    pkg = tmp_path / "deps_probe"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(_SRC_INIT, encoding="utf-8")
    (pkg / "core.py").write_text(
        "import os\n\nHOME = os.environ.get('HOME', '')\n", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def dirty_project(tmp_path: Path) -> Path:
    """Declares `requests` but never imports it — DEP002 unused dependency."""
    (tmp_path / "pyproject.toml").write_text(_DIRTY_PYPROJECT, encoding="utf-8")
    pkg = tmp_path / "deps_probe"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(_SRC_INIT, encoding="utf-8")
    (pkg / "core.py").write_text(
        "import os\n\nHOME = os.environ.get('HOME', '')\n", encoding="utf-8"
    )
    return tmp_path


@pytest.mark.slow
def test_deps_passes_on_clean_project(clean_project: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "harness.cli", "deps"],
        cwd=clean_project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"


@pytest.mark.slow
def test_deps_fails_on_unused_dependency(dirty_project: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "harness.cli", "deps"],
        cwd=dirty_project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "DEP002" in (result.stdout + result.stderr)


def test_deps_invokes_deptry_with_known_first_party(monkeypatch: pytest.MonkeyPatch) -> None:
    """In-process: cmd_deps builds a Task wrapping deptry + --known-first-party from src_dir."""
    from harness.runner import Task
    from harness.tasks import deps as deps_mod

    captured: dict[str, Task] = {}

    def fake_run(task: Task, **_: object) -> None:
        captured["task"] = task

    monkeypatch.setattr(deps_mod, "run", fake_run)
    deps_mod.cmd_deps()

    task = captured["task"]
    assert task.description == "Deps (deptry)"
    cmd = task.cmd
    assert any("deptry" in part for part in cmd), f"deptry missing in cmd: {cmd}"
    assert "--known-first-party" in cmd
    kfp_idx = cmd.index("--known-first-party")
    assert cmd[kfp_idx + 1] == "harness"
