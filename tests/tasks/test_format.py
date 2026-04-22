"""Integration tests for harness.tasks.format."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PYPROJECT = textwrap.dedent("""
    [project]
    name = "sample"
    version = "0.0.0"
    requires-python = ">=3.13"

    [tool.ruff]
    target-version = "py313"
    line-length = 99
""")

CLEAN = 'x = "hello"\n'
UNFORMATTED = "x   =   'hello'\n"


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    return tmp_path


def test_format_cli_clean_exits_zero(tmp_project: Path) -> None:
    f = tmp_project / "sample.py"
    f.write_text(CLEAN, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "harness.cli", "format"],
        cwd=tmp_project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert f.read_text(encoding="utf-8") == CLEAN


def test_format_cli_modifies_unformatted_file(tmp_project: Path) -> None:
    f = tmp_project / "sample.py"
    f.write_text(UNFORMATTED, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "harness.cli", "format"],
        cwd=tmp_project,
        capture_output=True,
        text=True,
        check=False,
    )
    # ruff format exits 0 even when it rewrites; contract is in-place modification.
    assert result.returncode == 0
    assert f.read_text(encoding="utf-8") != UNFORMATTED


def test_format_no_exit_does_not_raise(tmp_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from harness.tasks.format import cmd_format

    (tmp_project / "sample.py").write_text(UNFORMATTED, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    cmd_format(no_exit=True)  # must not raise SystemExit


def test_format_injects_bundled_config_in_bare_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from harness.tasks.format import task_format

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='bare'\nversion='0.0.0'\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    cmd = task_format().cmd
    assert "--config" in cmd
    assert Path(cmd[cmd.index("--config") + 1]).name == "ruff.toml"
