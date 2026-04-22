"""Project-local configuration: discover root, source/test dirs, runner, and invoker.

`load_config()` walks upward from CWD to find the nearest ``pyproject.toml`` — mirroring
pytest's rootdir algorithm — then layers ``[tool.harness]`` overrides on top of
autodetected defaults. Stdlib-only.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal

from harness.detect import (
    detect_features_dir,
    detect_src_dir,
    detect_test_dir,
    detect_test_invoker,
    detect_test_runner,
)

TestRunner = Literal["pytest", "unittest"]
TestInvoker = Literal["python", "uv"]
AcceptanceRunner = Literal["pytest-bdd", "behave", "off"]


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


@cache
def _load_pyproject(project_root: Path) -> dict[str, Any]:
    path = project_root / "pyproject.toml"
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _harness_table(pyproject: dict[str, Any]) -> dict[str, Any]:
    table = pyproject.get("tool", {}).get("harness", {})
    return table if isinstance(table, dict) else {}


def _user_global_config_path() -> Path:
    """``~/.config/harness/config.toml`` — respects ``$XDG_CONFIG_HOME``."""
    root = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(root) / "harness" / "config.toml"


def _user_global_table() -> dict[str, Any]:
    """Root-level keys from ``~/.config/harness/config.toml``, or ``{}`` on any failure.

    The file is dedicated to harness, so keys live at the root (no ``[tool.harness]``
    wrapper). Intended mainly for threshold overrides — same keys as pyproject's
    ``[tool.harness]``. Path fields (``src_dir``/``test_dir``) are project-specific
    and should not be set here.
    """
    path = _user_global_config_path()
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


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


def _acceptance_runner_override(table: dict[str, Any]) -> AcceptanceRunner | None:
    value = table.get("acceptance_runner")
    if value in ("pytest-bdd", "behave", "off"):
        return value
    return None


@dataclass(frozen=True)
class HarnessConfig:
    project_root: Path
    src_dir: Path
    test_dir: Path
    test_runner: TestRunner
    test_invoker: TestInvoker
    pytest_args: tuple[str, ...] = ()
    # Thresholds — overridable via `[tool.harness]`. Single source of truth for
    # every gate; individual tasks never hardcode these.
    coverage_min: int = 80
    crap_max: float = 30.0
    complexity_max_ccn: int = 15
    complexity_max_loc: int = 100
    complexity_max_args: int = 7
    mutation_min_coverage: float = 70.0
    mutation_max_runtime: int = 600
    mutation_min_score: float = 80.0
    enforce_crap: bool = True
    run_mutation_in_ci: bool = False
    enforce_mutation: bool = False
    # Acceptance (Gherkin) — all optional; resolved lazily by the task.
    acceptance_runner: AcceptanceRunner | None = None
    features_dir: Path | None = None
    run_acceptance_in_check: bool = False

    @property
    def pyproject(self) -> dict[str, Any]:
        """Parsed ``pyproject.toml`` for this project (cached process-wide)."""
        return _load_pyproject(self.project_root)

    def relpath(self, path: Path) -> str:
        """Project-root-relative string form of ``path`` (absolute path if outside)."""
        try:
            return str(path.relative_to(self.project_root))
        except ValueError:
            return str(path)

    @property
    def src_dir_arg(self) -> str:
        """Project-root-relative string form of ``src_dir`` for CLI arguments."""
        return self.relpath(self.src_dir)

    @property
    def test_dir_arg(self) -> str:
        """Project-root-relative string form of ``test_dir`` for CLI arguments."""
        return self.relpath(self.test_dir)

    @property
    def features_dir_arg(self) -> str | None:
        """Project-root-relative string form of ``features_dir``, or ``None``."""
        if self.features_dir is None:
            return None
        return self.relpath(self.features_dir)


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


def build_coverage_test_command(
    cfg: HarnessConfig, *, coverage_args: tuple[str, ...] = ()
) -> list[str]:
    """Build ``coverage run [coverage_args] -m <runner> ...`` using the configured invoker."""
    return [*invoker_prefix(cfg), "coverage", "run", *coverage_args, "-m", *_runner_argv(cfg)]


def load_config(start: Path | None = None) -> HarnessConfig:
    """Discover the project root and build a ``HarnessConfig``. Cached per project root."""
    return _load_config_cached(find_project_root(start))


@cache
def _load_config_cached(project_root: Path) -> HarnessConfig:
    pyproject = _load_pyproject(project_root)
    # Precedence (high → low): project [tool.harness] > ~/.config/harness/config.toml
    # > bundled dataclass defaults. `dict(user | project)` lets project keys override.
    table = {**_user_global_table(), **_harness_table(pyproject)}

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
    thresholds = _threshold_overrides(table)

    acceptance_runner = _acceptance_runner_override(table)
    features_dir_override = table.get("features_dir")
    features_dir = (
        (project_root / features_dir_override).resolve()
        if isinstance(features_dir_override, str)
        else detect_features_dir(project_root, test_dir)
    )
    run_acceptance_in_check = bool(table.get("run_acceptance_in_check"))

    return HarnessConfig(
        project_root=project_root,
        src_dir=src_dir,
        test_dir=test_dir,
        test_runner=test_runner,
        test_invoker=test_invoker,
        pytest_args=pytest_args,
        acceptance_runner=acceptance_runner,
        features_dir=features_dir,
        run_acceptance_in_check=run_acceptance_in_check,
        **thresholds,
    )


_INT_THRESHOLDS = (
    "coverage_min",
    "complexity_max_ccn",
    "complexity_max_loc",
    "complexity_max_args",
    "mutation_max_runtime",
)
_FLOAT_THRESHOLDS = ("crap_max", "mutation_min_coverage", "mutation_min_score")
_BOOL_THRESHOLDS = ("enforce_crap", "run_mutation_in_ci", "enforce_mutation")


def _threshold_overrides(table: dict[str, Any]) -> dict[str, Any]:
    """Parse known threshold keys from ``[tool.harness]`` with type coercion.

    Invalid values (non-numeric, wrong type) fall through silently — the
    dataclass default applies. Keeps config parsing permissive.
    """
    overrides: dict[str, Any] = {}
    for key in _INT_THRESHOLDS:
        value = _coerce_int(table.get(key))
        if value is not None:
            overrides[key] = value
    for key in _FLOAT_THRESHOLDS:
        value = _coerce_float(table.get(key))
        if value is not None:
            overrides[key] = value
    for key in _BOOL_THRESHOLDS:
        value = _coerce_bool(table.get(key))
        if value is not None:
            overrides[key] = value
    return overrides


def _coerce_int(raw: object) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    return None


def _coerce_float(raw: object) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


def _coerce_bool(raw: object) -> bool | None:
    if isinstance(raw, bool):
        return raw
    return None


def clear_cache() -> None:
    """Clear cached configuration — used by tests that mutate the project on disk."""
    _find_project_root_cached.cache_clear()
    _load_config_cached.cache_clear()
    _load_pyproject.cache_clear()
