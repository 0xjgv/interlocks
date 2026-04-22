"""Integration test for `cmd_coverage` — threshold enforcement via coverage.py."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

_MODULE_SRC = textwrap.dedent(
    """\
    def double(x):
        return x * 2
    """
)

_COVERING_TEST_SRC = textwrap.dedent(
    """\
    import unittest
    from mypkg.mod import double

    class TestDouble(unittest.TestCase):
        def test_double(self):
            self.assertEqual(double(3), 6)
    """
)

_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "cov-probe"
    version = "0.0.1"
    requires-python = ">=3.13"

    [tool.coverage.run]
    source = ["mypkg"]
    branch = true

    [tool.coverage.report]
    show_missing = true
    """
)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Project with `mypkg/mod.py` and an empty `tests/` dir."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(_MODULE_SRC, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    return tmp_path


def test_coverage_passes_when_threshold_met(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_project / "tests" / "test_mod.py").write_text(_COVERING_TEST_SRC, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    monkeypatch.syspath_prepend(str(tmp_project))

    from harness.tasks.coverage import cmd_coverage

    cmd_coverage(min_pct=80)  # 100% covered → no SystemExit


def test_coverage_fails_below_threshold(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # no tests → 0% on the module
    monkeypatch.chdir(tmp_project)
    monkeypatch.syspath_prepend(str(tmp_project))

    from harness.tasks.coverage import cmd_coverage

    with pytest.raises(SystemExit) as exc:
        cmd_coverage(min_pct=80)
    assert exc.value.code not in (0, None)
