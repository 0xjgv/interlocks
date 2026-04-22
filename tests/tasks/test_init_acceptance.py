"""Tests for `harness init-acceptance`."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "init-probe"
    version = "0.0.0"
    requires-python = ">=3.13"
    """
)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    return tmp_path


def _run_cli(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )


def test_init_acceptance_scaffolds_layout(tmp_project: Path) -> None:
    result = _run_cli(tmp_project, "init-acceptance")
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert (tmp_project / "tests" / "features" / "example.feature").is_file()
    assert (tmp_project / "tests" / "step_defs" / "test_example.py").is_file()
    assert (tmp_project / "tests" / "step_defs" / "conftest.py").is_file()
    feature = (tmp_project / "tests" / "features" / "example.feature").read_text(encoding="utf-8")
    assert "Scenario:" in feature


def test_init_acceptance_refuses_to_overwrite(tmp_project: Path) -> None:
    (tmp_project / "tests" / "features").mkdir()
    existing = tmp_project / "tests" / "features" / "example.feature"
    existing.write_text("# pre-existing\n", encoding="utf-8")
    result = _run_cli(tmp_project, "init-acceptance")
    assert result.returncode != 0
    assert existing.read_text(encoding="utf-8") == "# pre-existing\n"
    assert "refusing to overwrite" in result.stdout


def test_init_acceptance_in_process_scaffolds(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In-process call — lets coverage.py see the happy path."""
    monkeypatch.chdir(tmp_project)
    from harness.tasks.init_acceptance import cmd_init_acceptance

    cmd_init_acceptance()
    assert (tmp_project / "tests" / "features" / "example.feature").is_file()
    assert (tmp_project / "tests" / "step_defs" / "test_example.py").is_file()
    assert (tmp_project / "tests" / "step_defs" / "conftest.py").is_file()


def test_init_acceptance_in_process_refuses_overwrite(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In-process call — exercises the refuse-to-overwrite branch for coverage."""
    (tmp_project / "tests" / "features").mkdir()
    existing = tmp_project / "tests" / "features" / "example.feature"
    existing.write_text("# pre-existing\n", encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    from harness.tasks.init_acceptance import cmd_init_acceptance

    with pytest.raises(SystemExit):
        cmd_init_acceptance()
    assert existing.read_text(encoding="utf-8") == "# pre-existing\n"
