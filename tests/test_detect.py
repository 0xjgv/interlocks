"""Tests for harness.detect.detect_test_runner."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from harness import detect
from harness.detect import detect_test_runner


@pytest.fixture(autouse=True)
def _clear_detect_cache() -> None:
    detect_test_runner.cache_clear()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    # Force pytest-importability probe to fail unless a test opts in.
    monkeypatch.setattr(detect, "_pytest_importable", lambda: False)
    return tmp_path


def _write_pyproject(project: Path, contents: str) -> None:
    (project / "pyproject.toml").write_text(textwrap.dedent(contents), encoding="utf-8")


def test_override_pytest_wins(project: Path) -> None:
    _write_pyproject(
        project,
        """
        [tool.harness]
        test_runner = "pytest"
        """,
    )
    assert detect_test_runner() == "pytest"


def test_override_unittest_wins_even_with_pytest_config(project: Path) -> None:
    _write_pyproject(
        project,
        """
        [tool.harness]
        test_runner = "unittest"

        [tool.pytest.ini_options]
        minversion = "7.0"
        """,
    )
    assert detect_test_runner() == "unittest"


def test_tool_pytest_section_selects_pytest(project: Path) -> None:
    _write_pyproject(
        project,
        """
        [tool.pytest.ini_options]
        minversion = "7.0"
        """,
    )
    assert detect_test_runner() == "pytest"


def test_pytest_ini_file_selects_pytest(project: Path) -> None:
    (project / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    assert detect_test_runner() == "pytest"


def test_conftest_in_tests_selects_pytest(project: Path) -> None:
    tests = project / "tests"
    tests.mkdir()
    (tests / "conftest.py").write_text("", encoding="utf-8")
    assert detect_test_runner() == "pytest"


def test_pytest_in_project_dependencies_selects_pytest(project: Path) -> None:
    _write_pyproject(
        project,
        """
        [project]
        name = "sample"
        version = "0.0.0"
        dependencies = ["pytest>=8.0"]
        """,
    )
    assert detect_test_runner() == "pytest"


def test_pytest_in_dependency_group_selects_pytest(project: Path) -> None:
    _write_pyproject(
        project,
        """
        [project]
        name = "sample"
        version = "0.0.0"

        [dependency-groups]
        dev = ["pytest>=9.0"]
        """,
    )
    assert detect_test_runner() == "pytest"


def test_no_signals_no_importable_falls_back_to_unittest(project: Path) -> None:
    _write_pyproject(
        project,
        """
        [project]
        name = "sample"
        version = "0.0.0"
        """,
    )
    assert detect_test_runner() == "unittest"


def test_empty_repo_falls_back_to_unittest(project: Path) -> None:
    assert detect_test_runner() == "unittest"


def test_pytest_importable_selects_pytest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    detect_test_runner.cache_clear()
    monkeypatch.setattr(detect, "_pytest_importable", lambda: True)
    assert detect_test_runner() == "pytest"


def test_pytest_like_substring_does_not_match(project: Path) -> None:
    _write_pyproject(
        project,
        """
        [project]
        name = "sample"
        version = "0.0.0"
        dependencies = ["pytestify>=1.0"]
        """,
    )
    assert detect_test_runner() == "unittest"
