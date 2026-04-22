"""Integration tests for harness.tasks.test."""

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
""")

PASSING = textwrap.dedent("""
    import unittest

    class Passing(unittest.TestCase):
        def test_ok(self) -> None:
            self.assertEqual(1 + 1, 2)
""")

FAILING = textwrap.dedent("""
    import unittest

    class Failing(unittest.TestCase):
        def test_fail(self) -> None:
            self.assertEqual(1 + 1, 3)
""")


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    return tmp_path


@pytest.mark.parametrize(("source", "expected_rc"), [(PASSING, 0), (FAILING, 1)])
def test_test_cli(tmp_project: Path, source: str, expected_rc: int) -> None:
    (tmp_project / "tests" / "test_sample.py").write_text(source, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "harness.cli", "test"],
        cwd=tmp_project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected_rc


def test_test_passing_in_process(tmp_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from harness.tasks.test import cmd_test

    (tmp_project / "tests" / "test_sample.py").write_text(PASSING, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    cmd_test()  # no SystemExit on passing suite


def test_test_failing_in_process(tmp_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from harness.tasks.test import cmd_test

    (tmp_project / "tests" / "test_sample.py").write_text(FAILING, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    with pytest.raises(SystemExit) as exc:
        cmd_test()
    assert exc.value.code != 0
