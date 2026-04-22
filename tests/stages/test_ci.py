"""Integration tests for `harness ci` (format_check + lint + complexity + typecheck + coverage)."""

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

    [tool.coverage.run]
    source = ["harness"]
    branch = true

    [tool.coverage.report]
    fail_under = 80
    show_missing = true
    """
)

_INIT_SRC = '"""Tmp project package."""\n\nfrom harness.core import add\n\n__all__ = ["add"]\n'

_SRC = textwrap.dedent(
    '''\
    """Tiny module — fully covered by tests."""


    def add(a: int, b: int) -> int:
        return a + b
    '''
)

_TEST_SRC = textwrap.dedent(
    '''\
    """Tiny test — exercises the full module."""

    import unittest

    from harness.core import add


    class TestAdd(unittest.TestCase):
        def test_add(self) -> None:
            self.assertEqual(add(2, 3), 5)
    '''
)

_UNFORMATTED_SRC = "def add(a: int, b:int)->int:\n    return a+b\n"

_LINT_BAD_SRC = textwrap.dedent(
    '''\
    """Dirty."""

    import os


    def add(a: int, b: int) -> int:
        return a + b
    '''
)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    pkg = tmp_path / "harness"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(_INIT_SRC, encoding="utf-8")
    (pkg / "core.py").write_text(_SRC, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "test_add.py").write_text(_TEST_SRC, encoding="utf-8")
    return tmp_path


def _run_ci(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-P", "-m", "harness.cli", "ci"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_ci_passes_on_clean_project(tmp_project: Path) -> None:
    result = _run_ci(tmp_project)

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    out = result.stdout
    for marker in ("CI Checks", "Format check", "Lint check", "Complexity", "Type check"):
        assert marker in out, f"missing marker {marker!r}\n{out}"
    assert "Coverage" in out
    assert (tmp_project / ".coverage").exists()


@pytest.mark.parametrize(
    ("dirty_src", "expected_fragment"),
    [
        (_UNFORMATTED_SRC, "Format check"),
        (_LINT_BAD_SRC, "Lint check"),
    ],
    ids=["format", "lint"],
)
def test_ci_fails_on_violation(tmp_project: Path, dirty_src: str, expected_fragment: str) -> None:
    (tmp_project / "harness" / "core.py").write_text(dirty_src, encoding="utf-8")

    result = _run_ci(tmp_project)

    assert result.returncode != 0
    assert expected_fragment in result.stdout


def test_ci_in_process_queues_all_tasks(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Stub run_tasks — just verify cmd_ci composes the expected task list."""
    from harness.stages import ci as ci_mod

    descs: list[str] = []
    monkeypatch.setattr(
        ci_mod, "run_tasks", lambda tasks: descs.extend(t.description for t in tasks)
    )

    ci_mod.cmd_ci()

    assert descs == [
        "Format check",
        "Lint check",
        "Complexity (lizard)",
        "Deps (deptry)",
        "Type check",
        "Coverage >= 80%",
    ]
    assert "CI Checks" in capsys.readouterr().out
