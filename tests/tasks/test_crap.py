"""Integration test for `cmd_crap` — advisory CRAP gate over coverage.xml + lizard."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_MODULE_SRC = textwrap.dedent(
    """\
    def inc(x):
        return x + 1
    """
)

_TEST_SRC = textwrap.dedent(
    """\
    import unittest
    from harness.mod import inc

    class TestInc(unittest.TestCase):
        def test_inc(self):
            self.assertEqual(inc(1), 2)
    """
)

_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "crap-probe"
    version = "0.0.1"
    requires-python = ">=3.13"

    [tool.coverage.run]
    source = ["harness"]
    branch = true

    [tool.coverage.report]
    show_missing = true
    """
)


def _run_coverage(cwd: Path) -> None:
    """Run the project's unittest suite under coverage so `.coverage` exists."""
    cmd = [sys.executable, "-m", "coverage", "run", "-m", "unittest", "discover", "-s", "tests"]
    subprocess.run(cmd, cwd=cwd, check=True)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Project with `harness/mod.py` + covering test under `tests/`."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    pkg = tmp_path / "harness"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(_MODULE_SRC, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "test_mod.py").write_text(_TEST_SRC, encoding="utf-8")
    return tmp_path


def test_crap_advisory_does_not_exit(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_project)
    monkeypatch.syspath_prepend(str(tmp_project))
    # Prime .coverage so generate_coverage_xml has something to convert.
    _run_coverage(tmp_project)

    from harness.tasks.crap import cmd_crap

    cmd_crap()  # advisory — must never SystemExit on a healthy project

    captured = capsys.readouterr()
    assert "CRAP" in captured.out
