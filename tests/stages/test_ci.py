"""Integration tests for `harness ci` (format_check + lint + complexity + typecheck + coverage)."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.conftest import TmpProjectFactory

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
def tmp_project(make_tmp_project: TmpProjectFactory) -> Path:
    return make_tmp_project(
        pyproject=_PYPROJECT,
        src_files={
            "harness/__init__.py": _INIT_SRC,
            "harness/core.py": _SRC,
        },
        test_files={
            "__init__.py": "",
            "test_add.py": _TEST_SRC,
        },
    )


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
    markers = ("pyharness v", "CI Checks", "[format]", "[lint]", "[complexity]", "[typecheck]")
    for marker in markers:
        assert marker in out, f"missing marker {marker!r}\n{out}"
    assert "[coverage]" in out
    assert "Completed in" in out
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
    """Stub run_tasks + inline gates — verify cmd_ci composes the expected task list
    plus the sequential post-coverage gates."""
    from harness.config import load_config
    from harness.stages import ci as ci_mod

    parallel: list[str] = []
    sequential: list[str] = []
    monkeypatch.setattr(
        ci_mod, "run_tasks", lambda tasks: parallel.extend(t.description for t in tasks)
    )
    monkeypatch.setattr(ci_mod, "cmd_crap", lambda: sequential.append("CRAP"))
    monkeypatch.setattr(ci_mod, "cmd_mutation", lambda: sequential.append("Mutation"))

    ci_mod.cmd_ci()

    cfg = load_config()
    assert parallel == [
        "Format check",
        "Lint check",
        "Complexity (lizard)",
        "Deps (deptry)",
        "Type check",
        f"Coverage >= {cfg.coverage_min}%",
        "Architecture (import-linter)",
        "Acceptance (pytest-bdd)",
    ]
    expected_sequential = ["CRAP"] + (["Mutation"] if cfg.run_mutation_in_ci else [])
    assert sequential == expected_sequential
    assert "CI Checks" in capsys.readouterr().out


def test_ci_in_process_includes_mutation_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """`run_mutation_in_ci = true` → cmd_ci also runs cmd_mutation sequentially."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "ci-mut"
            version = "0.0.0"

            [tool.harness]
            run_mutation_in_ci = true
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    from harness.stages import ci as ci_mod

    sequential: list[str] = []
    monkeypatch.setattr(ci_mod, "run_tasks", lambda tasks: None)
    monkeypatch.setattr(ci_mod, "cmd_crap", lambda: sequential.append("CRAP"))
    monkeypatch.setattr(ci_mod, "cmd_mutation", lambda: sequential.append("Mutation"))

    ci_mod.cmd_ci()
    assert sequential == ["CRAP", "Mutation"]
