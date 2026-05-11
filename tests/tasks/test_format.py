"""Integration tests for interlocks.tasks.format."""

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
        [sys.executable, "-m", "interlocks.cli", "format"],
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
        [sys.executable, "-m", "interlocks.cli", "format"],
        cwd=tmp_project,
        capture_output=True,
        text=True,
        check=False,
    )
    # ruff format exits 0 even when it rewrites; contract is in-place modification.
    assert result.returncode == 0
    assert f.read_text(encoding="utf-8") != UNFORMATTED


def test_format_no_exit_does_not_raise(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from interlocks.tasks.format import cmd_format

    src = tmp_project / "sample.py"
    src.write_text(UNFORMATTED, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    cmd_format(no_exit=True)

    assert src.read_text(encoding="utf-8") != UNFORMATTED
    out = capsys.readouterr().out
    assert "[format]" in out


def test_format_injects_bundled_config_in_bare_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from interlocks.tasks.format import task_format

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='bare'\nversion='0.0.0'\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    cmd = task_format().cmd
    assert "--config" in cmd
    assert Path(cmd[cmd.index("--config") + 1]).name == "ruff.toml"


def test_format_omits_config_when_project_has_ruff_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ruff.toml sidecar: task_format must NOT pass --config."""
    from interlocks.tasks.format import task_format

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='bare'\nversion='0.0.0'\n", encoding="utf-8"
    )
    (tmp_path / "ruff.toml").write_text("line-length = 99\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert "--config" not in task_format().cmd


def test_format_still_injects_config_when_only_basedpyright_section_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[tool.basedpyright] must NOT suppress ruff --config for format (cross-tool isolation)."""
    from interlocks.tasks.format import task_format

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='bare'\nversion='0.0.0'\n\n"
        "[tool.basedpyright]\ntypeCheckingMode = 'standard'\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    cmd = task_format().cmd
    assert "--config" in cmd
    assert Path(cmd[cmd.index("--config") + 1]).name == "ruff.toml"
