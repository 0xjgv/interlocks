"""Tests for harness.config — project-root discovery, overrides, command builders."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from harness.config import (
    HarnessConfig,
    build_coverage_test_command,
    build_test_command,
    find_project_root,
    load_config,
)


def _write(path: Path, text: str) -> None:
    path.write_text(textwrap.dedent(text), encoding="utf-8")


# ─────────────── find_project_root ──────────────────────────────────


def test_find_project_root_walks_upward(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_project_root(nested) == tmp_path.resolve()


def test_find_project_root_falls_back_to_start_when_missing(tmp_path: Path) -> None:
    nested = tmp_path / "x"
    nested.mkdir()
    assert find_project_root(nested) == nested.resolve()


# ─────────────── load_config defaults (autodetect) ──────────────────


@pytest.fixture
def tmp_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "tests").mkdir()
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    _write(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "mypkg"
        version = "0.0.0"
        dependencies = ["pytest>=9"]
        """,
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_load_config_autodetects(tmp_project: Path) -> None:
    cfg = load_config()
    assert cfg.project_root == tmp_project.resolve()
    assert cfg.src_dir == (tmp_project / "mypkg").resolve()
    assert cfg.test_dir == (tmp_project / "tests").resolve()
    assert cfg.test_runner == "pytest"
    assert cfg.test_invoker == "python"
    assert cfg.pytest_args == ()


def test_load_config_uv_lock_flips_invoker(tmp_project: Path) -> None:
    (tmp_project / "uv.lock").write_text("", encoding="utf-8")
    assert load_config().test_invoker == "uv"


# ─────────────── threshold defaults + overrides ─────────────────────


def test_threshold_defaults_when_absent(tmp_project: Path) -> None:
    cfg = load_config()
    assert cfg.coverage_min == 80
    assert cfg.crap_max == 30.0
    assert cfg.complexity_max_ccn == 15
    assert cfg.complexity_max_loc == 100
    assert cfg.complexity_max_args == 7
    assert cfg.mutation_min_coverage == 70.0
    assert cfg.mutation_max_runtime == 600
    assert cfg.mutation_min_score == 80.0
    assert cfg.enforce_crap is True
    assert cfg.run_mutation_in_ci is False
    assert cfg.enforce_mutation is False


def test_threshold_overrides_apply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "tests").mkdir()
    _write(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "thresh"
        version = "0.0.0"

        [tool.harness]
        coverage_min = 90
        crap_max = 25.5
        complexity_max_ccn = 12
        complexity_max_loc = 80
        complexity_max_args = 5
        mutation_min_coverage = 85.0
        mutation_max_runtime = 300
        mutation_min_score = 92.5
        enforce_crap = false
        run_mutation_in_ci = true
        enforce_mutation = true
        """,
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.coverage_min == 90
    assert cfg.crap_max == 25.5
    assert cfg.complexity_max_ccn == 12
    assert cfg.complexity_max_loc == 80
    assert cfg.complexity_max_args == 5
    assert cfg.mutation_min_coverage == 85.0
    assert cfg.mutation_max_runtime == 300
    assert cfg.mutation_min_score == 92.5
    assert cfg.enforce_crap is False
    assert cfg.run_mutation_in_ci is True
    assert cfg.enforce_mutation is True


def test_invalid_threshold_types_fall_back_to_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "tests").mkdir()
    _write(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "badthresh"
        version = "0.0.0"

        [tool.harness]
        coverage_min = "eighty"
        crap_max = true
        """,
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.coverage_min == 80
    assert cfg.crap_max == 30.0


# ─────────────── user-global cascade ────────────────────────────────


def test_user_global_config_overrides_bundled_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``~/.config/harness/config.toml`` (root keys) applies when project has none."""
    (tmp_path / "tests").mkdir()
    _write(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "ug"
        version = "0.0.0"
        """,
    )
    home = tmp_path / "fake_home"
    (home / ".config" / "harness").mkdir(parents=True)
    (home / ".config" / "harness" / "config.toml").write_text(
        "coverage_min = 88\ncrap_max = 20.0\n", encoding="utf-8"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.coverage_min == 88
    assert cfg.crap_max == 20.0


def test_project_tool_harness_overrides_user_global(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Project `[tool.harness]` wins over ``~/.config/harness/config.toml``."""
    (tmp_path / "tests").mkdir()
    _write(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "pwins"
        version = "0.0.0"

        [tool.harness]
        coverage_min = 95
        """,
    )
    home = tmp_path / "fake_home"
    (home / ".config" / "harness").mkdir(parents=True)
    (home / ".config" / "harness" / "config.toml").write_text(
        "coverage_min = 88\ncrap_max = 20.0\n", encoding="utf-8"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.coverage_min == 95  # project wins
    assert cfg.crap_max == 20.0  # user-global fills in for missing keys


def test_malformed_user_global_is_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A broken user-global file must not crash load_config — just use defaults."""
    (tmp_path / "tests").mkdir()
    _write(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "broken-ug"
        version = "0.0.0"
        """,
    )
    home = tmp_path / "fake_home"
    (home / ".config" / "harness").mkdir(parents=True)
    (home / ".config" / "harness" / "config.toml").write_text(
        "not = [valid toml\n", encoding="utf-8"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.chdir(tmp_path)
    cfg = load_config()  # must not raise
    assert cfg.coverage_min == 80


# ─────────────── load_config overrides ──────────────────────────────


def test_overrides_win_over_autodetect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "spec").mkdir()
    (tmp_path / "source").mkdir()
    _write(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "sample"
        version = "0.0.0"

        [tool.harness]
        src_dir = "source"
        test_dir = "spec"
        test_runner = "unittest"
        test_invoker = "uv"
        pytest_args = ["-x", "--tb=short"]
        """,
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.src_dir == (tmp_path / "source").resolve()
    assert cfg.test_dir == (tmp_path / "spec").resolve()
    assert cfg.test_runner == "unittest"
    assert cfg.test_invoker == "uv"
    assert cfg.pytest_args == ("-x", "--tb=short")


def test_invalid_runner_override_falls_back_to_detect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "tests").mkdir()
    _write(
        tmp_path / "pyproject.toml",
        """
        [tool.harness]
        test_runner = "nose"
        """,
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    # Bad value is ignored — detection falls through; no pytest signals → unittest.
    assert cfg.test_runner in ("pytest", "unittest")


# ─────────────── command builders ───────────────────────────────────


_FAKE_ROOT = Path("/proj")


def _cfg(**overrides: object) -> HarnessConfig:
    defaults = {
        "project_root": _FAKE_ROOT,
        "src_dir": _FAKE_ROOT / "mypkg",
        "test_dir": _FAKE_ROOT / "tests",
        "test_runner": "pytest",
        "test_invoker": "python",
        "pytest_args": (),
    }
    defaults.update(overrides)
    return HarnessConfig(**defaults)  # type: ignore[arg-type]


def test_build_test_command_python_pytest() -> None:
    cfg = _cfg()
    assert build_test_command(cfg) == [sys.executable, "-m", "pytest", "tests", "-q"]


def test_build_test_command_pytest_appends_pytest_args() -> None:
    cfg = _cfg(pytest_args=("-x", "--tb=short"))
    expected = [sys.executable, "-m", "pytest", "tests", "-q", "-x", "--tb=short"]
    assert build_test_command(cfg) == expected


def test_build_test_command_uv_pytest() -> None:
    cfg = _cfg(test_invoker="uv")
    assert build_test_command(cfg) == ["uv", "run", "pytest", "tests", "-q"]


def test_build_test_command_unittest_discover() -> None:
    cfg = _cfg(test_runner="unittest")
    expected = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"]
    assert build_test_command(cfg) == expected


def test_build_coverage_test_command_pytest() -> None:
    cfg = _cfg()
    assert build_coverage_test_command(cfg) == [
        sys.executable,
        "-m",
        "coverage",
        "run",
        "-m",
        "pytest",
        "tests",
        "-q",
    ]


def test_build_coverage_test_command_uv() -> None:
    cfg = _cfg(test_invoker="uv", test_runner="unittest")
    assert build_coverage_test_command(cfg) == [
        "uv",
        "run",
        "coverage",
        "run",
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
        "-q",
    ]
