"""CRAP enforcement: `enforce_crap` flips advisory ↔ blocking."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from harness.metrics import CrapRow

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

_PYPROJECT_COV = textwrap.dedent(
    """\
    [project]
    name = "crap-enforce"
    version = "0.0.1"
    requires-python = ">=3.13"

    [tool.coverage.run]
    source = ["harness"]
    branch = true
    """
)


def _run_coverage(cwd: Path) -> None:
    cmd = [sys.executable, "-m", "coverage", "run", "-m", "unittest", "discover", "-s", "tests"]
    subprocess.run(cmd, cwd=cwd, check=True)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT_COV, encoding="utf-8")
    pkg = tmp_path / "harness"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(_MODULE_SRC, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "test_mod.py").write_text(_TEST_SRC, encoding="utf-8")
    return tmp_path


def _write_pyproject(project: Path, *, enforce: bool) -> None:
    (project / "pyproject.toml").write_text(
        _PYPROJECT_COV
        + f"\n[tool.harness]\ncrap_max = 0.5\nenforce_crap = {str(enforce).lower()}\n",
        encoding="utf-8",
    )


def test_crap_exits_when_enforced(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """crap_max = 0.5 < CRAP(inc) = 1 + enforce_crap=true → SystemExit(1)."""
    _write_pyproject(tmp_project, enforce=True)
    monkeypatch.chdir(tmp_project)
    monkeypatch.syspath_prepend(str(tmp_project))
    monkeypatch.setattr(sys, "argv", ["harness", "crap"])
    _run_coverage(tmp_project)

    from harness.tasks.crap import cmd_crap

    with pytest.raises(SystemExit) as excinfo:
        cmd_crap()
    assert excinfo.value.code == 1

    captured = capsys.readouterr()
    assert "1 function(s) exceed" in captured.out


def test_crap_stays_advisory_when_disabled(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Same offender + enforce_crap=false → no SystemExit, message still printed."""
    _write_pyproject(tmp_project, enforce=False)
    monkeypatch.chdir(tmp_project)
    monkeypatch.syspath_prepend(str(tmp_project))
    monkeypatch.setattr(sys, "argv", ["harness", "crap"])
    _run_coverage(tmp_project)

    from harness.tasks.crap import cmd_crap

    cmd_crap()  # must not raise

    captured = capsys.readouterr()
    assert "1 function(s) exceed" in captured.out


def test_cached_crap_advisory_skips_without_coverage(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from harness.config import clear_cache
    from harness.tasks.crap import cmd_crap_cached_advisory

    monkeypatch.chdir(tmp_project)
    clear_cache()
    try:
        cmd_crap_cached_advisory()
    finally:
        clear_cache()

    assert "no coverage cache" in capsys.readouterr().out


def test_cached_crap_advisory_skips_stale_coverage(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from harness.config import clear_cache
    from harness.tasks.crap import cmd_crap_cached_advisory

    cov_cache = tmp_project / ".coverage"
    cov_cache.write_text("old", encoding="utf-8")
    os.utime(cov_cache, (1, 1))
    monkeypatch.chdir(tmp_project)
    clear_cache()
    try:
        cmd_crap_cached_advisory()
    finally:
        clear_cache()

    assert "coverage cache is stale" in capsys.readouterr().out


def test_cached_crap_advisory_reports_fresh_offenders(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from harness.config import clear_cache
    from harness.tasks import crap as crap_mod

    cov_cache = tmp_project / ".coverage"
    cov_cache.write_text("fresh", encoding="utf-8")
    future = max(p.stat().st_mtime for p in tmp_project.rglob("*.py")) + 10
    os.utime(cov_cache, (future, future))
    (tmp_project / "coverage.xml").write_text("<coverage />", encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(crap_mod, "generate_coverage_xml", lambda: Path("coverage.xml"))
    monkeypatch.setattr(crap_mod, "parse_coverage", lambda path: {})
    monkeypatch.setattr(crap_mod, "lizard_functions", lambda src: [])
    monkeypatch.setattr(
        crap_mod,
        "compute_crap_rows",
        lambda *args, **kwargs: [
            CrapRow(
                path="harness/mod.py",
                name="inc",
                start=1,
                end=2,
                ccn=10,
                loc=2,
                coverage=0.0,
                crap=110.0,
            )
        ],
    )
    clear_cache()
    try:
        crap_mod.cmd_crap_cached_advisory()
    finally:
        clear_cache()

    out = capsys.readouterr().out
    assert "inc@1-2@harness/mod.py" in out
    assert "cached advisory" in out
