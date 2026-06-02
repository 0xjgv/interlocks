"""Integration test for `cmd_crap` — CRAP gate over coverage.xml + lizard."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from interlocks.config import clear_cache

_MODULE_SRC = textwrap.dedent(
    """\
    def inc(x):
        return x + 1
    """
)

_TEST_SRC = textwrap.dedent(
    """\
    import unittest
    from interlocks.mod import inc

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
    requires-python = ">=3.11"

    [tool.coverage.run]
    source = ["interlocks"]
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
    """Project with `interlocks/mod.py` + covering test under `tests/`."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    pkg = tmp_path / "interlocks"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(_MODULE_SRC, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "test_mod.py").write_text(_TEST_SRC, encoding="utf-8")
    return tmp_path


def test_crap_passes_on_healthy_project(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No offenders → no SystemExit regardless of enforce_crap (default True)."""
    monkeypatch.chdir(tmp_project)
    monkeypatch.syspath_prepend(str(tmp_project))
    monkeypatch.setattr("interlocks.ui.is_verbose", lambda: False)
    # Prime .coverage so generate_coverage_xml has something to convert.
    _run_coverage(tmp_project)

    from interlocks.tasks.crap import cmd_crap

    cmd_crap()  # trivial inc() is under the ceiling

    captured = capsys.readouterr()
    assert "CRAP" in captured.out
    assert "[crap]" in captured.out
    assert "ok" in captured.out


def test_crap_default_threshold_from_config(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`[tool.interlocks] crap_max = 5.0` surfaces in the 'all below N' success line."""
    (tmp_project / "pyproject.toml").write_text(
        _PYPROJECT + "\n[tool.interlocks]\ncrap_max = 5.0\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_project)
    monkeypatch.syspath_prepend(str(tmp_project))
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "crap"])  # no --max= override
    _run_coverage(tmp_project)

    from interlocks.tasks.crap import cmd_crap

    cmd_crap()
    captured = capsys.readouterr()
    assert "5.0" in captured.out


def test_crap_cli_max_overrides_config(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--max=N` on argv wins over `[tool.interlocks] crap_max`."""
    (tmp_project / "pyproject.toml").write_text(
        _PYPROJECT + "\n[tool.interlocks]\ncrap_max = 5.0\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_project)
    monkeypatch.syspath_prepend(str(tmp_project))
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "crap", "--max=42.5"])
    _run_coverage(tmp_project)

    from interlocks.tasks.crap import cmd_crap

    cmd_crap()
    captured = capsys.readouterr()
    assert "42.5" in captured.out


def test_crap_json_passes_on_healthy_project(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_project)
    monkeypatch.syspath_prepend(str(tmp_project))
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "crap", "--json"])
    _run_coverage(tmp_project)

    from interlocks.tasks.crap import cmd_crap

    clear_cache()
    try:
        cmd_crap()
    finally:
        clear_cache()

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["command"] == "crap"
    assert payload["passed"] is True
    assert payload["status"] == "ok"
    assert payload["max_crap"] == 30.0
    assert payload["function_count"] >= 1
    assert payload["offender_count"] == 0
    assert payload["offenders"] == []
    assert captured.err == "interlocks: [crap] CRAP --max=30.0 running\n"


def test_crap_json_reports_enforced_offenders(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_project / "pyproject.toml").write_text(
        _PYPROJECT + "\n[tool.interlocks]\ncrap_max = 0.5\nenforce_crap = true\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_project)
    monkeypatch.syspath_prepend(str(tmp_project))
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "crap", "--json"])
    _run_coverage(tmp_project)

    from interlocks.tasks.crap import cmd_crap

    clear_cache()
    try:
        with pytest.raises(SystemExit) as excinfo:
            cmd_crap()
    finally:
        clear_cache()

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["passed"] is False
    assert payload["status"] == "failed"
    assert payload["enforce_crap"] is True
    assert payload["offender_count"] == 1
    assert payload["offenders"][0]["name"] == "inc"
    assert payload["offenders"][0]["crap"] == 1.0
    assert "inc@" not in captured.out


def test_crap_json_keeps_advisory_offenders_non_blocking(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_project / "pyproject.toml").write_text(
        _PYPROJECT + "\n[tool.interlocks]\ncrap_max = 0.5\nenforce_crap = false\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_project)
    monkeypatch.syspath_prepend(str(tmp_project))
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "crap", "--json"])
    _run_coverage(tmp_project)

    from interlocks.tasks.crap import cmd_crap

    clear_cache()
    try:
        cmd_crap()
    finally:
        clear_cache()

    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert payload["status"] == "warn"
    assert payload["enforce_crap"] is False
    assert payload["offender_count"] == 1


def test_crap_json_missing_coverage_cache_is_parseable(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "crap", "--json"])

    from interlocks.tasks.crap import cmd_crap

    clear_cache()
    try:
        with pytest.raises(SystemExit) as excinfo:
            cmd_crap()
    finally:
        clear_cache()

    assert excinfo.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is False
    assert payload["status"] == "skipped"
    assert payload["reason"] == "no coverage cache"
    assert payload["next_action"] == (
        "Run `interlocks gate coverage` before `interlocks gate crap`."
    )


def test_crap_json_stale_coverage_cache_is_parseable(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_project / ".coverage").write_text("old", encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "crap", "--json"])
    monkeypatch.setattr("interlocks.tasks.crap.coverage_cache_is_stale", lambda *_args: True)

    from interlocks.tasks.crap import cmd_crap

    clear_cache()
    try:
        with pytest.raises(SystemExit) as excinfo:
            cmd_crap()
    finally:
        clear_cache()

    assert excinfo.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is False
    assert payload["status"] == "skipped"
    assert payload["reason"] == "coverage cache is stale"
    assert payload["next_action"] == (
        "Run `interlocks gate coverage` before `interlocks gate crap`."
    )
