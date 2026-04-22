"""Project-local configuration: discover root, source/test dirs, runner, and invoker.

`load_config()` walks upward from CWD to find the nearest ``pyproject.toml`` — mirroring
pytest's rootdir algorithm — then layers ``[tool.harness]`` overrides on top of
autodetected defaults. Stdlib-only.
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal

from harness.detect import (
    detect_src_dir,
    detect_test_dir,
    detect_test_invoker,
    detect_test_runner,
)

TestRunner = Literal["pytest", "unittest"]
TestInvoker = Literal["python", "uv"]


def find_project_root(start: Path | None = None) -> Path:
    """Walk up from ``start`` (CWD by default) to the first dir with ``pyproject.toml``.

    Falls back to the resolved ``start`` if no ``pyproject.toml`` is found on the way
    up to the filesystem root.
    """
    return _find_project_root_cached((start or Path.cwd()).resolve())


@cache
def _find_project_root_cached(origin: Path) -> Path:
    for candidate in (origin, *origin.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return origin


def _load_pyproject(project_root: Path) -> dict[str, Any]:
    path = project_root / "pyproject.toml"
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _harness_table(pyproject: dict[str, Any]) -> dict[str, Any]:
    table = pyproject.get("tool", {}).get("harness", {})
    return table if isinstance(table, dict) else {}


def _runner_override(table: dict[str, Any]) -> TestRunner | None:
    value = table.get("test_runner")
    if value == "pytest":
        return "pytest"
    if value == "unittest":
        return "unittest"
    return None


def _invoker_override(table: dict[str, Any]) -> TestInvoker | None:
    value = table.get("test_invoker")
    if value == "python":
        return "python"
    if value == "uv":
        return "uv"
    return None


@dataclass(frozen=True)
class HarnessConfig:
    project_root: Path
    src_dir: Path
    test_dir: Path
    test_runner: TestRunner
    test_invoker: TestInvoker
    pytest_args: tuple[str, ...] = ()

    @property
    def src_dir_arg(self) -> str:
        """Project-root-relative string form of ``src_dir`` for CLI arguments."""
        return _relative_str(self.src_dir, self.project_root)

    @property
    def test_dir_arg(self) -> str:
        """Project-root-relative string form of ``test_dir`` for CLI arguments."""
        return _relative_str(self.test_dir, self.project_root)


def _relative_str(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def invoker_prefix(cfg: HarnessConfig) -> list[str]:
    """Argv prefix for invoking a Python module under the configured invoker."""
    if cfg.test_invoker == "uv":
        return ["uv", "run"]
    return [sys.executable, "-m"]


def _runner_argv(cfg: HarnessConfig) -> list[str]:
    """Runner-specific argv tail — shared by the plain and coverage-wrapped commands."""
    if cfg.test_runner == "pytest":
        return ["pytest", cfg.test_dir_arg, "-q", *cfg.pytest_args]
    return ["unittest", "discover", "-s", cfg.test_dir_arg, "-q"]


def build_test_command(cfg: HarnessConfig) -> list[str]:
    """Build the full `harness test` command from ``cfg``."""
    return [*invoker_prefix(cfg), *_runner_argv(cfg)]


def build_coverage_test_command(cfg: HarnessConfig) -> list[str]:
    """Build ``coverage run -m <runner> ...`` using the configured invoker."""
    return [*invoker_prefix(cfg), "coverage", "run", "-m", *_runner_argv(cfg)]


def load_config(start: Path | None = None) -> HarnessConfig:
    """Discover the project root and build a ``HarnessConfig``. Cached per project root."""
    return _load_config_cached(find_project_root(start))


@cache
def _load_config_cached(project_root: Path) -> HarnessConfig:
    pyproject = _load_pyproject(project_root)
    table = _harness_table(pyproject)

    test_dir_override = table.get("test_dir")
    src_dir_override = table.get("src_dir")
    runner_override = _runner_override(table)
    invoker_override = _invoker_override(table)
    pytest_args = tuple(str(a) for a in (table.get("pytest_args") or ()))

    test_dir = (
        (project_root / test_dir_override).resolve()
        if isinstance(test_dir_override, str)
        else detect_test_dir(project_root)
    )
    src_dir = (
        (project_root / src_dir_override).resolve()
        if isinstance(src_dir_override, str)
        else detect_src_dir(project_root, pyproject)
    )
    test_runner: TestRunner = runner_override or detect_test_runner(
        project_root, pyproject, test_dir
    )
    test_invoker: TestInvoker = invoker_override or detect_test_invoker(project_root)

    return HarnessConfig(
        project_root=project_root,
        src_dir=src_dir,
        test_dir=test_dir,
        test_runner=test_runner,
        test_invoker=test_invoker,
        pytest_args=pytest_args,
    )


def clear_cache() -> None:
    """Clear cached configuration — used by tests that mutate the project on disk."""
    _find_project_root_cached.cache_clear()
    _load_config_cached.cache_clear()
