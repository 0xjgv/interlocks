"""Integration tests for `interlocks check` (fix + format + typecheck + test + suppressions)."""

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

_INIT_SRC = '"""Tmp project package."""\n\nfrom interlocks.core import add\n\n__all__ = ["add"]\n'

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

    from interlocks.core import add


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
            "interlocks/__init__.py": _INIT_SRC,
            "interlocks/core.py": _CLEAN_SRC,
        },
        test_files={
            "__init__.py": "",
            "test_add.py": _TEST_SRC,
        },
    )


def _run_check(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-P", "-m", "interlocks.cli", "check"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_check_passes_on_clean_project(tmp_project: Path) -> None:
    result = _run_check(tmp_project)

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    out = result.stdout
    assert "interlocks v" in out
    assert "Quality Checks" in out
    assert "Parallel" in out
    assert "Advisory" in out
    assert "[fix]" in out
    assert "[format]" in out
    assert "[typecheck]" in out
    assert "[test]" in out
    assert "Suppressions" in out
    assert "Completed in" in out


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
    (tmp_project / "interlocks" / "core.py").write_text(dirty, encoding="utf-8")

    result = _run_check(tmp_project)

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "import os" not in (tmp_project / "interlocks" / "core.py").read_text(encoding="utf-8")


def test_check_in_process_dispatches_stages(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Stub fix/format/run_tasks + suppressions; confirm cmd_check orchestrates them."""
    from interlocks.stages import check as check_mod

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
    monkeypatch.setattr(check_mod, "cmd_crap_cached_advisory", lambda: calls.append("cached-crap"))
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
        "cached-crap",
        "suppressions",
    ]
    out = capsys.readouterr().out
    assert "Quality Checks" in out
    assert "Parallel" in out
    assert "Advisory" in out
    assert "Completed in" in out


def test_check_in_process_runs_suppressions_on_failure(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Suppressions report is in a `finally` — runs even when an inner stage raises."""
    from interlocks.stages import check as check_mod

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


def _run_check_quiet(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-P", "-m", "interlocks.cli", "check", "--quiet"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_check_quiet_success_is_one_verdict_line(tmp_project: Path) -> None:
    result = _run_check_quiet(tmp_project)

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    out = result.stdout
    assert "interlocks v" not in out
    assert "Quality Checks" not in out
    assert "Parallel" not in out
    assert "Advisory" not in out
    assert "Suppressions" not in out
    assert "Completed in" not in out
    assert out.strip().splitlines()[-1].startswith("check: ok — ")


def test_check_quiet_failure_emits_failed_verdict(tmp_project: Path) -> None:
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

    result = _run_check_quiet(tmp_project)

    assert result.returncode != 0
    out = result.stdout
    assert "Quality Checks" not in out
    assert "[test]" in out  # failing row preserved
    assert any(line.startswith("check: FAILED — ") for line in out.splitlines()), out


# ─────────────── require_acceptance + run_acceptance_in_check ───────────────


def _write_require_acceptance_check_project(
    tmp_path: Path, *, run_acceptance_in_check: bool
) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            f"""\
            [project]
            name = "check-req-acc"
            version = "0.0.0"

            [tool.interlocks]
            require_acceptance = true
            run_acceptance_in_check = {"true" if run_acceptance_in_check else "false"}
            """
        ),
        encoding="utf-8",
    )


def _capture_check_parallel_descriptions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> list[str]:
    from interlocks.stages import check as check_mod

    captured: list[str] = []
    monkeypatch.setattr(check_mod, "cmd_fix", lambda: None)
    monkeypatch.setattr(check_mod, "cmd_format", lambda: None)
    monkeypatch.setattr(
        check_mod, "run_tasks", lambda tasks: captured.extend(t.description for t in tasks)
    )
    monkeypatch.setattr(check_mod, "run", lambda task, **_kw: None)
    monkeypatch.setattr(check_mod, "cmd_crap_cached_advisory", lambda: None)
    monkeypatch.setattr(check_mod, "print_suppressions_report", lambda: None)
    monkeypatch.chdir(tmp_path)
    check_mod.cmd_check()
    return captured


def test_check_does_not_fail_required_when_run_acceptance_in_check_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`require_acceptance = true` is gated to ci unless `run_acceptance_in_check = true`."""
    _write_require_acceptance_check_project(tmp_path, run_acceptance_in_check=False)

    descriptions = _capture_check_parallel_descriptions(tmp_path, monkeypatch)

    assert "Acceptance (required)" not in descriptions
    assert "Acceptance (pytest-bdd)" not in descriptions


def test_check_appends_required_failure_when_both_flags_true(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Both flags on + missing features/ → check enforces the required failure task."""
    _write_require_acceptance_check_project(tmp_path, run_acceptance_in_check=True)

    descriptions = _capture_check_parallel_descriptions(tmp_path, monkeypatch)

    assert "Acceptance (required)" in descriptions


def test_check_appends_required_failure_when_behavior_coverage_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_require_acceptance_check_project(tmp_path, run_acceptance_in_check=True)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            'name = "check-req-acc"', 'name = "interlocks"'
        )
        + 'features_dir = "tests/features"\n',
        encoding="utf-8",
    )
    features = tmp_path / "tests" / "features"
    features.mkdir(parents=True)
    (features / "smoke.feature").write_text(
        "Feature: smoke\n  Scenario: it works\n    Given a thing\n",
        encoding="utf-8",
    )

    descriptions = _capture_check_parallel_descriptions(tmp_path, monkeypatch)

    assert "Acceptance (required)" in descriptions
    assert "Acceptance (pytest-bdd)" not in descriptions


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
