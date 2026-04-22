"""Integration tests for `harness check` (fix + format + typecheck + test + suppressions)."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "tmpproj"
    version = "0.0.1"
    requires-python = ">=3.13"

    [tool.ruff]
    target-version = "py313"
    line-length = 99

    [tool.ruff.lint]
    select = ["E", "F", "I"]

    [tool.basedpyright]
    pythonVersion = "3.13"
    typeCheckingMode = "standard"
    reportMissingTypeStubs = false
    """
)

_INIT_SRC = '"""Tmp project package."""\n\nfrom harness.core import add\n\n__all__ = ["add"]\n'

_CLEAN_SRC = textwrap.dedent(
    '''\
    """Tiny module."""


    def add(a: int, b: int) -> int:
        return a + b
    '''
)

_TEST_SRC = textwrap.dedent(
    '''\
    """Tiny test."""

    import unittest

    from harness.core import add


    class TestAdd(unittest.TestCase):
        def test_add(self) -> None:
            self.assertEqual(add(2, 3), 5)
    '''
)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    pkg = tmp_path / "harness"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(_INIT_SRC, encoding="utf-8")
    (pkg / "core.py").write_text(_CLEAN_SRC, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "test_add.py").write_text(_TEST_SRC, encoding="utf-8")
    return tmp_path


def _run_check(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-P", "-m", "harness.cli", "check"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_check_passes_on_clean_project(tmp_project: Path) -> None:
    result = _run_check(tmp_project)

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    out = result.stdout
    assert "Quality Checks" in out
    assert "Fix lint errors" in out
    assert "Format code" in out
    assert "Type check" in out
    assert "Run tests" in out
    assert "Suppressions" in out


def test_check_fixes_trivially_fixable_lint(tmp_project: Path) -> None:
    """Unused-import should be auto-fixed by `ruff check --fix`; check still passes."""
    dirty = textwrap.dedent(
        '''\
        """Tiny module with an unused import."""

        import os  # will be removed by ruff --fix


        def add(a: int, b: int) -> int:
            return a + b
        '''
    )
    (tmp_project / "harness" / "core.py").write_text(dirty, encoding="utf-8")

    result = _run_check(tmp_project)

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "import os" not in (tmp_project / "harness" / "core.py").read_text(encoding="utf-8")


def test_check_fails_when_tests_fail(tmp_project: Path) -> None:
    failing = textwrap.dedent(
        '''\
        """Failing test."""

        import unittest


        class TestBroken(unittest.TestCase):
            def test_broken(self) -> None:
                self.assertEqual(1, 2)
        '''
    )
    (tmp_project / "tests" / "test_add.py").write_text(failing, encoding="utf-8")

    result = _run_check(tmp_project)

    assert result.returncode != 0
    # Suppressions report runs in `finally`, so it must still appear.
    assert "Suppressions" in result.stdout
