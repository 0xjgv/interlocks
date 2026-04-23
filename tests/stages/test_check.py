"""Integration tests for `harness check` (fix + format + typecheck + test + suppressions)."""

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
def tmp_project(make_tmp_project: TmpProjectFactory) -> Path:
    return make_tmp_project(
        pyproject=_PYPROJECT,
        src_files={
            "harness/__init__.py": _INIT_SRC,
            "harness/core.py": _CLEAN_SRC,
        },
        test_files={
            "__init__.py": "",
            "test_add.py": _TEST_SRC,
        },
    )


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


def test_check_in_process_dispatches_stages(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Stub fix/format/run_tasks + suppressions; confirm cmd_check orchestrates them."""
    from harness.stages import check as check_mod

    calls: list[object] = []
    monkeypatch.setattr(check_mod, "cmd_fix", lambda: calls.append("fix"))
    monkeypatch.setattr(check_mod, "cmd_format", lambda: calls.append("format"))
    monkeypatch.setattr(
        check_mod,
        "run_tasks",
        lambda tasks: calls.append(("run_tasks", [t.description for t in tasks])),
    )
    monkeypatch.setattr(
        check_mod,
        "run",
        lambda task, **kw: calls.append(("run", task.description, kw)),
    )
    monkeypatch.setattr(
        check_mod, "print_suppressions_report", lambda: calls.append("suppressions")
    )

    monkeypatch.chdir(tmp_project)
    check_mod.cmd_check()

    assert calls == [
        "fix",
        "format",
        ("run_tasks", ["Type check", "Run tests"]),
        ("run", "Deps (deptry)", {"no_exit": True}),
        "suppressions",
    ]
    assert "Quality Checks" in capsys.readouterr().out


def test_check_in_process_runs_suppressions_on_failure(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Suppressions report is in a `finally` — runs even when an inner stage raises."""
    from harness.stages import check as check_mod

    calls: list[str] = []
    monkeypatch.setattr(check_mod, "cmd_fix", lambda: calls.append("fix"))

    def boom() -> None:
        raise SystemExit(2)

    monkeypatch.setattr(check_mod, "cmd_format", boom)
    monkeypatch.setattr(check_mod, "run_tasks", lambda tasks: calls.append("run_tasks"))
    monkeypatch.setattr(
        check_mod, "print_suppressions_report", lambda: calls.append("suppressions")
    )

    monkeypatch.chdir(tmp_project)
    with pytest.raises(SystemExit):
        check_mod.cmd_check()
    assert calls == ["fix", "suppressions"]


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
