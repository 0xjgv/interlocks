"""Integration tests for harness.tasks.lint."""

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

    [tool.ruff.lint]
    select = ["E", "F"]
""")

CLEAN = "x = 1\n"
VIOLATING = "x = y\n"  # F821 undefined-name


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(("source", "expected_rc"), [(CLEAN, 0), (VIOLATING, 1)])
def test_lint_cli(tmp_project: Path, source: str, expected_rc: int) -> None:
    (tmp_project / "sample.py").write_text(source, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "harness.cli", "lint"],
        cwd=tmp_project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected_rc


def test_lint_clean_in_process(tmp_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from harness.tasks.lint import cmd_lint

    (tmp_project / "sample.py").write_text(CLEAN, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    cmd_lint()  # no SystemExit on clean input


def test_lint_violating_in_process(tmp_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from harness.tasks.lint import cmd_lint

    (tmp_project / "sample.py").write_text(VIOLATING, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    with pytest.raises(SystemExit) as exc:
        cmd_lint()
    assert exc.value.code != 0


# ─────────────── bundled ruff defaults fallback ─────────────────────


_BARE_PYPROJECT = textwrap.dedent("""
    [project]
    name = "bare"
    version = "0.0.0"
    requires-python = ">=3.13"
""")


def test_lint_injects_bundled_config_when_project_has_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bare project with no [tool.ruff]: task_lint must pass --config <bundled>."""
    from harness.tasks.lint import task_lint

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    cmd = task_lint().cmd
    assert "--config" in cmd
    cfg_path = Path(cmd[cmd.index("--config") + 1])
    assert cfg_path.name == "ruff.toml"
    assert cfg_path.is_file()


def test_lint_omits_config_when_project_has_tool_ruff(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Project with [tool.ruff]: task_lint must NOT pass --config."""
    from harness.tasks.lint import task_lint

    monkeypatch.chdir(tmp_project)
    assert "--config" not in task_lint().cmd


def test_lint_omits_config_when_project_has_ruff_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Project with ruff.toml sidecar: task_lint must NOT pass --config."""
    from harness.tasks.lint import task_lint

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    (tmp_path / "ruff.toml").write_text("line-length = 99\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert "--config" not in task_lint().cmd
