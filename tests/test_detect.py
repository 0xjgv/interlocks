"""Tests for interlocks.detect — pure helpers: runner, dirs, invoker."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from interlocks.config import load_config
from interlocks.detect import (
    detect_src_dir,
    detect_test_dir,
    detect_test_invoker,
)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write_pyproject(project: Path, contents: str) -> None:
    (project / "pyproject.toml").write_text(textwrap.dedent(contents), encoding="utf-8")


def _runner_for(project: Path) -> str:
    return load_config(project).test_runner


# ─────────────── test runner detection ──────────────────────────────


def test_tool_pytest_section_selects_pytest(project: Path) -> None:
    _write_pyproject(
        project,
        """
        [tool.pytest.ini_options]
        minversion = "7.0"
        """,
    )
    assert _runner_for(project) == "pytest"


def test_pytest_ini_file_selects_pytest(project: Path) -> None:
    (project / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    assert _runner_for(project) == "pytest"


def test_conftest_in_tests_selects_pytest(project: Path) -> None:
    tests = project / "tests"
    tests.mkdir()
    (tests / "conftest.py").write_text("", encoding="utf-8")
    assert _runner_for(project) == "pytest"


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
    assert _runner_for(project) == "pytest"


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
    assert _runner_for(project) == "pytest"


def test_no_signals_no_importable_falls_back_to_unittest(project: Path) -> None:
    _write_pyproject(
        project,
        """
        [project]
        name = "sample"
        version = "0.0.0"
        """,
    )
    assert _runner_for(project) == "unittest"


def test_empty_repo_falls_back_to_unittest(project: Path) -> None:
    assert _runner_for(project) == "unittest"


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
    assert _runner_for(project) == "unittest"


# ─────────────── test-dir detection ─────────────────────────────────


def test_detect_test_dir_prefers_tests(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "test").mkdir()
    assert detect_test_dir(tmp_path) == (tmp_path / "tests")


def test_detect_test_dir_falls_through_to_test(tmp_path: Path) -> None:
    (tmp_path / "test").mkdir()
    assert detect_test_dir(tmp_path) == (tmp_path / "test")


def test_detect_test_dir_recognizes_src_tests_layout(tmp_path: Path) -> None:
    (tmp_path / "src" / "tests").mkdir(parents=True)
    assert detect_test_dir(tmp_path) == (tmp_path / "src" / "tests")


def test_detect_test_dir_defaults_to_tests_when_missing(tmp_path: Path) -> None:
    assert detect_test_dir(tmp_path) == (tmp_path / "tests")


# ─────────────── src-dir detection ──────────────────────────────────


def test_detect_src_dir_flat_layout_picks_package_dir(tmp_path: Path) -> None:
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    assert detect_src_dir(tmp_path, {}) == pkg.resolve()


def test_detect_src_dir_src_layout_picks_sub_package(tmp_path: Path) -> None:
    inner = tmp_path / "src" / "mypkg"
    inner.mkdir(parents=True)
    (inner / "__init__.py").write_text("", encoding="utf-8")
    assert detect_src_dir(tmp_path, {}) == inner.resolve()


def test_detect_src_dir_uv_build_backend_override(tmp_path: Path) -> None:
    pkg = tmp_path / "custom_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    pyproject = {
        "tool": {"uv": {"build-backend": {"module-name": "custom_pkg", "module-root": ""}}}
    }
    assert detect_src_dir(tmp_path, pyproject) == pkg.resolve()


def test_detect_src_dir_hatch_packages(tmp_path: Path) -> None:
    pkg = tmp_path / "pkgroot"
    pkg.mkdir()
    pyproject = {"tool": {"hatch": {"build": {"targets": {"wheel": {"packages": ["pkgroot"]}}}}}}
    assert detect_src_dir(tmp_path, pyproject) == pkg.resolve()


def test_detect_src_dir_skips_tests_dir(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "mypkg").mkdir()
    (tmp_path / "mypkg" / "__init__.py").write_text("", encoding="utf-8")
    assert detect_src_dir(tmp_path, {}) == (tmp_path / "mypkg").resolve()


def test_detect_src_dir_skips_properties_dir(tmp_path: Path) -> None:
    properties = tmp_path / "properties"
    properties.mkdir()
    (properties / "__init__.py").write_text("", encoding="utf-8")
    (properties / "test_example_properties.py").write_text(
        "def test_example():\n    pass\n", encoding="utf-8"
    )

    assert detect_src_dir(tmp_path, {}) == tmp_path.resolve()


def test_detect_src_dir_allows_real_properties_package(tmp_path: Path) -> None:
    properties = tmp_path / "properties"
    properties.mkdir()
    (properties / "__init__.py").write_text("", encoding="utf-8")

    assert detect_src_dir(tmp_path, {}) == properties.resolve()


# ─────────────── test-invoker detection ─────────────────────────────


def test_detect_test_invoker_defaults_to_python(tmp_path: Path) -> None:
    assert detect_test_invoker(tmp_path) == "python"


def test_detect_test_invoker_uv_when_lock_present(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    assert detect_test_invoker(tmp_path) == "uv"
