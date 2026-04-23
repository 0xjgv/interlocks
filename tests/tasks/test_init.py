"""Tests for `harness init` (greenfield scaffold)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def _run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_init_scaffolds_greenfield_project(tmp_path: Path) -> None:
    result = _run_cli(tmp_path, "init")
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    pyproject = tmp_path / "pyproject.toml"
    assert pyproject.is_file()
    body = pyproject.read_text(encoding="utf-8")
    assert f'name = "{tmp_path.name}"' in body
    assert 'requires-python = ">=3.13"' in body
    assert "dependencies = []" in body
    assert 'dev = ["pytest>=8"]' in body
    assert "[tool.harness]" in body
    assert (tmp_path / "tests" / "__init__.py").is_file()
    smoke = tmp_path / "tests" / "test_smoke.py"
    assert smoke.is_file()
    assert "def test_smoke()" in smoke.read_text(encoding="utf-8")


def test_init_refuses_to_overwrite_existing_pyproject(tmp_path: Path) -> None:
    existing = tmp_path / "pyproject.toml"
    existing.write_text("# pre-existing\n", encoding="utf-8")
    result = _run_cli(tmp_path, "init")
    assert result.returncode != 0
    assert existing.read_text(encoding="utf-8") == "# pre-existing\n"
    assert not (tmp_path / "tests").exists()
    assert "refusing to overwrite" in result.stdout


def test_init_in_process_scaffolds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """In-process call — lets coverage.py see the happy path."""
    monkeypatch.chdir(tmp_path)
    from harness.tasks.init import cmd_init

    cmd_init()
    assert (tmp_path / "pyproject.toml").is_file()
    assert (tmp_path / "tests" / "__init__.py").is_file()
    assert (tmp_path / "tests" / "test_smoke.py").is_file()


def test_init_in_process_refuses_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In-process call — exercises the refuse-to-overwrite branch for coverage."""
    existing = tmp_path / "pyproject.toml"
    existing.write_text("# pre-existing\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    from harness.tasks.init import cmd_init

    with pytest.raises(SystemExit):
        cmd_init()
    assert existing.read_text(encoding="utf-8") == "# pre-existing\n"
    assert not (tmp_path / "tests").exists()


def test_task_init_returns_none() -> None:
    from harness.tasks.init import task_init

    assert task_init() is None
