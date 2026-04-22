"""Integration + unit tests for `harness arch` (import-linter contracts)."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "arch-probe"
    version = "0.0.1"
    requires-python = ">=3.13"
    dependencies = []

    [build-system]
    requires = ["setuptools>=61"]
    build-backend = "setuptools.build_meta"
    """
)

_SRC_INIT = '"""Src package."""\n\nVALUE = 1\n'
_TEST_INIT = '"""Tests package."""\n'
_CLEAN_TEST = textwrap.dedent(
    '''\
    """Clean test."""

    import unittest

    from arch_probe import VALUE


    class TestValue(unittest.TestCase):
        def test_value(self) -> None:
            self.assertEqual(VALUE, 1)
    '''
)


_PIN_DIRS = textwrap.dedent(
    """
    [tool.harness]
    src_dir = "arch_probe"
    test_dir = "tests"
    """
)

_DIRTY_INIT = textwrap.dedent(
    '''\
    """Src package that wrongly imports tests."""

    from tests import test_value  # noqa: F401
    '''
)


@pytest.fixture
def clean_project(tmp_path: Path) -> Path:
    """src and tests both packages; src does NOT import tests — default contract passes."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT + _PIN_DIRS, encoding="utf-8")
    src = tmp_path / "arch_probe"
    src.mkdir()
    (src / "__init__.py").write_text(_SRC_INIT, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text(_TEST_INIT, encoding="utf-8")
    (tests / "test_value.py").write_text(_CLEAN_TEST, encoding="utf-8")
    return tmp_path


@pytest.fixture
def dirty_project(clean_project: Path) -> Path:
    """Same layout, but src imports a test helper — default contract MUST fail."""
    (clean_project / "arch_probe" / "__init__.py").write_text(_DIRTY_INIT, encoding="utf-8")
    return clean_project


@pytest.fixture
def non_package_tests(tmp_path: Path) -> Path:
    """tests/ has no __init__.py — default contract can't be built, should skip gracefully."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT + _PIN_DIRS, encoding="utf-8")
    src = tmp_path / "arch_probe"
    src.mkdir()
    (src / "__init__.py").write_text(_SRC_INIT, encoding="utf-8")
    (tmp_path / "tests").mkdir()  # no __init__.py
    return tmp_path


@pytest.mark.slow
def test_arch_passes_on_clean_project(clean_project: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "harness.cli", "arch"],
        cwd=clean_project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"


@pytest.mark.slow
def test_arch_fails_when_src_imports_tests(dirty_project: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "harness.cli", "arch"],
        cwd=dirty_project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Production does not import tests" in (result.stdout + result.stderr)


@pytest.mark.slow
def test_arch_skips_when_tests_not_a_package(non_package_tests: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "harness.cli", "arch"],
        cwd=non_package_tests,
        capture_output=True,
        text=True,
        check=False,
    )
    # Skipped gracefully: exit 0 and a nudge message.
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "arch:" in result.stdout
    assert "default needs" in result.stdout


def test_task_arch_uses_user_contracts_when_declared(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If pyproject has [tool.importlinter], we invoke lint-imports without --config."""
    from harness.tasks import arch as arch_mod

    fake_cfg_dir = tmp_path / "proj"
    fake_cfg_dir.mkdir()
    (fake_cfg_dir / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [tool.importlinter]
            root_package = "anything"
            """
        ),
        encoding="utf-8",
    )

    class FakeCfg:
        project_root = fake_cfg_dir
        src_dir = fake_cfg_dir / "src"
        test_dir = fake_cfg_dir / "tests"

    monkeypatch.setattr(arch_mod, "load_config", FakeCfg)
    task = arch_mod.task_arch()
    assert task is not None
    assert task.description == "Architecture (import-linter)"
    assert "--config" not in task.cmd


def test_task_arch_synthesizes_default_when_no_contracts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No contracts + both dirs are packages → we build a temp INI and pass --config."""
    from harness.tasks import arch as arch_mod

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    src = proj / "pkg"
    src.mkdir()
    (src / "__init__.py").write_text("", encoding="utf-8")
    tests = proj / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")

    class FakeCfg:
        project_root = proj
        src_dir = src
        test_dir = tests

    monkeypatch.setattr(arch_mod, "load_config", FakeCfg)
    task = arch_mod.task_arch()
    assert task is not None
    assert task.description == "Architecture (default: src ↛ tests)"
    assert "--config" in task.cmd
    cfg_path = Path(task.cmd[task.cmd.index("--config") + 1])
    contents = cfg_path.read_text(encoding="utf-8")
    assert "type = forbidden" in contents
    assert "pkg" in contents and "tests" in contents


def test_task_arch_returns_none_when_tests_not_a_package(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from harness.tasks import arch as arch_mod

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    src = proj / "pkg"
    src.mkdir()
    (src / "__init__.py").write_text("", encoding="utf-8")
    (proj / "tests").mkdir()  # no __init__.py

    class FakeCfg:
        project_root = proj
        src_dir = src
        test_dir = proj / "tests"

    monkeypatch.setattr(arch_mod, "load_config", FakeCfg)
    assert arch_mod.task_arch() is None
