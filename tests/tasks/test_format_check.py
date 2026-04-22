"""Integration tests for harness.tasks.format_check.

``format-check`` is not registered in the CLI TASKS dict (see harness/cli.py),
so we invoke ``cmd_format_check`` directly and assert the SystemExit code.
"""

from __future__ import annotations

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


def test_format_check_clean_exits_zero(tmp_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from harness.tasks.format_check import cmd_format_check

    (tmp_project / "sample.py").write_text(CLEAN, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    cmd_format_check()  # returns without raising SystemExit


def test_format_check_unformatted_exits_nonzero(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from harness.tasks.format_check import cmd_format_check

    (tmp_project / "sample.py").write_text(UNFORMATTED, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    with pytest.raises(SystemExit) as excinfo:
        cmd_format_check()
    assert excinfo.value.code != 0


def test_format_check_injects_bundled_config_in_bare_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from harness.tasks.format_check import task_format_check

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='bare'\nversion='0.0.0'\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    cmd = task_format_check().cmd
    assert "--config" in cmd
    assert Path(cmd[cmd.index("--config") + 1]).name == "ruff.toml"
