"""Integration tests for interlocks.tasks.fix."""

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
    requires-python = ">=3.11"

    [tool.ruff]
    target-version = "py311"
    line-length = 99

    [tool.ruff.lint]
    select = ["F", "I"]
""")

CLEAN = "x = 1\n"
# Unused import — ruff auto-removes it under F401.
FIXABLE = "import os\nimport sys\n\nprint(sys.version)\n"


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    return tmp_path


def test_fix_cli_clean_exits_zero(tmp_project: Path) -> None:
    f = tmp_project / "sample.py"
    f.write_text(CLEAN, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "fix"],
        cwd=tmp_project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert f.read_text(encoding="utf-8") == CLEAN


def test_fix_cli_modifies_fixable_file(tmp_project: Path) -> None:
    f = tmp_project / "sample.py"
    f.write_text(FIXABLE, encoding="utf-8")
    subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "fix"],
        cwd=tmp_project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "import os" not in f.read_text(encoding="utf-8")


def test_fix_no_exit_does_not_raise(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from interlocks.tasks.fix import cmd_fix

    # F821 undefined-name — ruff can't auto-fix, exits 1.
    src = tmp_project / "sample.py"
    src.write_text("x = undefined_name\n", encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    cmd_fix(no_exit=True)

    assert src.read_text(encoding="utf-8") == "x = undefined_name\n"
    out = capsys.readouterr().out
    assert "[fix]" in out


def test_fix_injects_bundled_config_in_bare_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from interlocks.tasks.fix import task_fix

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='bare'\nversion='0.0.0'\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    cmd = task_fix().cmd
    assert "--config" in cmd
    assert Path(cmd[cmd.index("--config") + 1]).name == "ruff.toml"
