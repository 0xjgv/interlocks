"""Project-local configuration: discover root, source/test dirs, runner, and invoker.

`load_config()` walks upward from CWD to find the nearest ``pyproject.toml`` — mirroring
pytest's rootdir algorithm — then layers ``[tool.harness]`` overrides on top of
autodetected defaults. Stdlib-only.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, Literal

from harness.detect import (
    detect_features_dir,
    detect_src_dir,
    detect_target_interpreter,
    detect_test_dir,
    detect_test_invoker,
    detect_test_runner,
)

TestRunner = Literal["pytest", "unittest"]
TestInvoker = Literal["python", "uv"]
AcceptanceRunner = Literal["pytest-bdd", "behave", "off"]
MutationCIMode = Literal["off", "incremental", "full"]
Preset = Literal["baseline", "strict", "legacy"]

_SOURCE_AUTO = "auto-detected"
_SOURCE_DEFAULT = "bundled-default"
_SOURCE_PRESET = "preset-derived"
_SOURCE_PROJECT = "project-configured"
_SOURCE_USER = "user-global"

_SUPPORTED_PRESETS: tuple[Preset, ...] = ("baseline", "strict", "legacy")
_PRESET_DESCRIPTIONS: dict[Preset, str] = {
    "baseline": "adoption defaults; advisory CRAP; mutation off in CI; acceptance off in check",
    "strict": "mature repo defaults; CRAP and mutation blocking; mutation full in CI",
    "legacy": "ratcheting defaults; permissive thresholds; advisory gates",
}
_PRESET_DEFAULTS: dict[Preset, dict[str, object]] = {
    "baseline": {
        "coverage_min": 70,
        "crap_max": 40.0,
        "complexity_max_ccn": 18,
        "complexity_max_loc": 120,
        "complexity_max_args": 8,
        "mutation_min_coverage": 60.0,
        "mutation_max_runtime": 600,
        "mutation_min_score": 70.0,
        "enforce_crap": False,
        "run_mutation_in_ci": False,
        "enforce_mutation": False,
        "mutation_ci_mode": "off",
        "run_acceptance_in_check": False,
    },
    "strict": {
        "coverage_min": 90,
        "crap_max": 20.0,
        "complexity_max_ccn": 10,
        "complexity_max_loc": 80,
        "complexity_max_args": 5,
        "mutation_min_coverage": 80.0,
        "mutation_max_runtime": 900,
        "mutation_min_score": 85.0,
        "enforce_crap": True,
        "run_mutation_in_ci": True,
        "enforce_mutation": True,
        "mutation_ci_mode": "full",
        "run_acceptance_in_check": True,
    },
    "legacy": {
        "coverage_min": 0,
        "crap_max": 80.0,
        "complexity_max_ccn": 30,
        "complexity_max_loc": 250,
        "complexity_max_args": 12,
        "mutation_min_coverage": 0.0,
        "mutation_max_runtime": 300,
        "mutation_min_score": 0.0,
        "enforce_crap": False,
        "run_mutation_in_ci": False,
        "enforce_mutation": False,
        "mutation_ci_mode": "off",
        "run_acceptance_in_check": False,
    },
}


def supported_presets() -> tuple[Preset, ...]:
    """Return supported preset names in display order."""
    return _SUPPORTED_PRESETS


def preset_defaults(preset: Preset) -> dict[str, object]:
    """Return a copy of the defaults applied by ``preset``."""
    return dict(_PRESET_DEFAULTS[preset])


def preset_description(preset: Preset) -> str:
    """Return the human-readable description for ``preset``."""
    return _PRESET_DESCRIPTIONS[preset]


def kv_with_source(cfg: HarnessConfig, key: str, value: object) -> tuple[str, str]:
    """Render a ``(key, "value (source)")`` row using ``cfg.value_sources``."""
    source = cfg.value_sources.get(key, "unknown")
    return (key, f"{value} ({source})")


class HarnessConfigError(Exception):
    """Raised when project configuration is missing or malformed."""


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


def _mutation_ci_mode_override(table: dict[str, Any]) -> MutationCIMode | None:
    value = table.get("mutation_ci_mode")
    if value in ("off", "incremental", "full"):
        return value
    return None


@dataclass(frozen=True)
class HarnessConfig:
    project_root: Path
    src_dir: Path
    test_dir: Path
    test_runner: TestRunner
    test_invoker: TestInvoker
    preset: Preset | None = None
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
    # Dormant — consumed by a future `harness mutation --since=<ref>` feature.
    mutation_ci_mode: MutationCIMode = "off"
    mutation_since_ref: str = "origin/main"
    # Acceptance (Gherkin) — all optional; resolved lazily by the task.
    acceptance_runner: AcceptanceRunner | None = None
    features_dir: Path | None = None
    run_acceptance_in_check: bool = False
    value_sources: dict[str, str] = field(default_factory=dict)
    unsupported_presets: tuple[str, ...] = ()

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
    """Argv prefix for invoking a Python module under the configured invoker.

    Prefers the target project's ``.venv/bin/python`` when ``invoker == "python"``, so
    tools run against the project's own dependencies rather than pipx's venv. Falls
    back to ``sys.executable`` when the project has no in-tree venv.
    """
    if cfg.test_invoker == "uv":
        return ["uv", "run"]
    venv_python = detect_target_interpreter(cfg.project_root)
    if venv_python is not None:
        return [str(venv_python), "-m"]
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


def require_pyproject(cfg: HarnessConfig) -> None:
    """Raise ``HarnessConfigError`` when ``cfg.project_root`` has no ``pyproject.toml``.

    ``find_project_root`` falls back to CWD when no ancestor has a ``pyproject.toml`` —
    running gates against that bogus root produces confusing downstream errors. Call
    this at the CLI boundary to fail fast with an actionable message.
    """
    if not (cfg.project_root / "pyproject.toml").is_file():
        raise HarnessConfigError("no pyproject.toml — run `harness init` to scaffold")


@cache
def _load_config_cached(project_root: Path) -> HarnessConfig:
    pyproject = _load_pyproject(project_root)
    user_table = _user_global_table()
    project_table = _harness_table(pyproject)
    table, value_sources, preset, unsupported_presets = _resolve_config_table(
        user_table, project_table
    )

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
    run_acceptance_override = _coerce_bool(table.get("run_acceptance_in_check"))
    run_acceptance_in_check = (
        run_acceptance_override
        if run_acceptance_override is not None
        else HarnessConfig.run_acceptance_in_check
    )

    mutation_ci_mode = _mutation_ci_mode_override(table) or HarnessConfig.mutation_ci_mode
    since_ref_raw = table.get("mutation_since_ref")
    mutation_since_ref = (
        since_ref_raw if isinstance(since_ref_raw, str) else HarnessConfig.mutation_since_ref
    )

    return HarnessConfig(
        project_root=project_root,
        src_dir=src_dir,
        test_dir=test_dir,
        test_runner=test_runner,
        test_invoker=test_invoker,
        preset=preset,
        pytest_args=pytest_args,
        acceptance_runner=acceptance_runner,
        features_dir=features_dir,
        run_acceptance_in_check=run_acceptance_in_check,
        mutation_ci_mode=mutation_ci_mode,
        mutation_since_ref=mutation_since_ref,
        value_sources=_complete_value_sources(
            value_sources,
            table,
            test_dir_override=test_dir_override,
            src_dir_override=src_dir_override,
            runner_override=runner_override,
            invoker_override=invoker_override,
            acceptance_runner=acceptance_runner,
            features_dir_override=features_dir_override,
        ),
        unsupported_presets=unsupported_presets,
        **thresholds,
    )


_STRING_KEYS = ("src_dir", "test_dir", "mutation_since_ref", "features_dir")
_ENUM_PARSERS = {
    "test_runner": _runner_override,
    "test_invoker": _invoker_override,
    "acceptance_runner": _acceptance_runner_override,
    "mutation_ci_mode": _mutation_ci_mode_override,
}


def _resolve_config_table(
    user_table: dict[str, Any], project_table: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, str], Preset | None, tuple[str, ...]]:
    """Resolve config using preset defaults before explicit values per layer."""
    resolved: dict[str, Any] = {}
    sources: dict[str, str] = {}
    active_preset: Preset | None = None
    unsupported: list[str] = []

    for table, source in ((user_table, _SOURCE_USER), (project_table, _SOURCE_PROJECT)):
        preset = _preset_override(table)
        if preset is not None:
            resolved.update(_PRESET_DEFAULTS[preset])
            sources.update(dict.fromkeys(_PRESET_DEFAULTS[preset], _SOURCE_PRESET))
            resolved["preset"] = preset
            sources["preset"] = source
            active_preset = preset
        elif isinstance(table.get("preset"), str):
            unsupported.append(f"{source}: {table['preset']}")

        explicit = _explicit_config_overrides(table)
        resolved.update(explicit)
        sources.update(dict.fromkeys(explicit, source))

    return resolved, sources, active_preset, tuple(unsupported)


def _preset_override(table: dict[str, Any]) -> Preset | None:
    value = table.get("preset")
    if value in _SUPPORTED_PRESETS:
        return value
    return None


def _explicit_config_overrides(table: dict[str, Any]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for key in _STRING_KEYS:
        value = table.get(key)
        if isinstance(value, str):
            overrides[key] = value
    value = table.get("pytest_args")
    if isinstance(value, list):
        overrides["pytest_args"] = value
    for key, parser in _ENUM_PARSERS.items():
        parsed = parser(table)
        if parsed is not None:
            overrides[key] = parsed
    overrides.update(_threshold_overrides(table))
    value = _coerce_bool(table.get("run_acceptance_in_check"))
    if value is not None:
        overrides["run_acceptance_in_check"] = value
    return overrides


def _complete_value_sources(
    sources: dict[str, str],
    table: dict[str, Any],
    *,
    test_dir_override: object,
    src_dir_override: object,
    runner_override: TestRunner | None,
    invoker_override: TestInvoker | None,
    acceptance_runner: AcceptanceRunner | None,
    features_dir_override: object,
) -> dict[str, str]:
    complete = dict(sources)
    default_keys = (
        *_INT_THRESHOLDS,
        *_FLOAT_THRESHOLDS,
        *_BOOL_THRESHOLDS,
        "mutation_ci_mode",
        "mutation_since_ref",
        "run_acceptance_in_check",
    )
    for key in default_keys:
        complete.setdefault(key, _SOURCE_DEFAULT)
    for key, value in {
        "src_dir": src_dir_override,
        "test_dir": test_dir_override,
        "test_runner": runner_override,
        "test_invoker": invoker_override,
        "features_dir": features_dir_override,
        "acceptance_runner": acceptance_runner,
    }.items():
        if value is None:
            complete[key] = _SOURCE_AUTO
        else:
            complete.setdefault(key, _SOURCE_PROJECT if key in table else _SOURCE_USER)
    complete.setdefault("pytest_args", _SOURCE_DEFAULT)
    complete.setdefault(
        "preset", _SOURCE_DEFAULT if table.get("preset") is None else _SOURCE_PROJECT
    )
    return complete


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
