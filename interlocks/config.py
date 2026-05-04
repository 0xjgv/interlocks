"""Project-local configuration: discover root, source/test dirs, runner, and invoker.

`load_config()` walks upward from CWD to find the nearest ``pyproject.toml`` — mirroring
pytest's rootdir algorithm — then layers ``[tool.interlocks]`` overrides on top of
autodetected defaults. Stdlib-only.
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, Literal

from interlocks.behavior_coverage import INTERLOCKS_REGISTRY
from interlocks.detect import (
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
AuditSeverityThreshold = Literal["low", "medium", "high", "critical"]
Preset = Literal["baseline", "strict", "legacy"]

_SOURCE_AUTO = "auto-detected"
_SOURCE_DEFAULT = "bundled-default"
_SOURCE_PRESET = "preset-derived"
_SOURCE_PROJECT = "project-configured"

_SUPPORTED_PRESETS: tuple[Preset, ...] = ("baseline", "strict", "legacy")
_PRESET_DESCRIPTIONS: dict[Preset, str] = {
    "baseline": "adoption defaults; advisory CRAP; mutation off in CI; acceptance off in check",
    "strict": "mature repo defaults; CRAP, mutation, and acceptance blocking; mutation full in CI",
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
        "require_acceptance": False,
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
        "require_acceptance": True,
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
        "require_acceptance": False,
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


def kv_with_source(cfg: InterlockConfig, key: str, value: object) -> tuple[str, str]:
    """Render a ``(key, "value (source)")`` row using ``cfg.value_sources``."""
    source = cfg.value_sources.get(key, "unknown")
    return (key, f"{value} ({source})")


ConfigKeyGroup = Literal[
    "Paths",
    "Runner",
    "Preset",
    "Thresholds",
    "Gates",
    "Mutation",
    "Acceptance",
    "Dependencies",
    "Evidence",
]


@dataclass(frozen=True)
class ConfigKeyDoc:
    """Documentation entry for one ``[tool.interlocks]`` key.

    Source of truth for descriptions, types, and section grouping rendered by
    ``interlocks config``. The dataclass remains the source of truth for
    runtime values and defaults; this table only adds human-readable metadata.
    """

    name: str
    type: str
    default: str
    description: str
    group: ConfigKeyGroup


CONFIG_KEYS: tuple[ConfigKeyDoc, ...] = (
    ConfigKeyDoc(
        "src_dir",
        "str",
        "auto",
        "Source dir (autodetected from src/<pkg>, top-level pkg, or build-backend)",
        "Paths",
    ),
    ConfigKeyDoc(
        "test_dir",
        "str",
        "auto",
        "Test dir (first existing of tests/, test/, src/tests/)",
        "Paths",
    ),
    ConfigKeyDoc(
        "features_dir",
        "str",
        "auto",
        "Gherkin features dir (tests/features/, features/, or <test_dir>/features/)",
        "Paths",
    ),
    ConfigKeyDoc(
        "test_runner",
        "pytest|unittest",
        "auto",
        "Test runner — autodetected from pytest config/deps/imports",
        "Runner",
    ),
    ConfigKeyDoc(
        "test_invoker",
        "python|uv",
        "auto",
        "Invocation prefix — uv when uv.lock present, else python",
        "Runner",
    ),
    ConfigKeyDoc(
        "pytest_args",
        "list[str]",
        "[]",
        "Extra args appended to pytest commands",
        "Runner",
    ),
    ConfigKeyDoc(
        "preset",
        "baseline|strict|legacy",
        "(none)",
        "Apply a preset bundle of defaults; explicit keys still win",
        "Preset",
    ),
    ConfigKeyDoc("coverage_min", "int", "80", "coverage.py fail-under", "Thresholds"),
    ConfigKeyDoc(
        "crap_max",
        "float",
        "30.0",
        "CRAP ceiling: complexity * (1 - coverage)^2",
        "Thresholds",
    ),
    ConfigKeyDoc("complexity_max_ccn", "int", "15", "lizard CCN cap", "Thresholds"),
    ConfigKeyDoc("complexity_max_args", "int", "7", "lizard argument count cap", "Thresholds"),
    ConfigKeyDoc("complexity_max_loc", "int", "100", "lizard LOC cap per function", "Thresholds"),
    ConfigKeyDoc("enforce_crap", "bool", "true", "CRAP exits 1 on offenders", "Gates"),
    ConfigKeyDoc(
        "enforce_behavior_attribution",
        "bool",
        "auto",
        "Behavior-attribution exits 1 on runtime attribution failures; auto-on for interlocks",
        "Gates",
    ),
    ConfigKeyDoc(
        "run_mutation_in_ci",
        "bool",
        "false",
        "Include mutation in `interlocks ci`",
        "Gates",
    ),
    ConfigKeyDoc(
        "enforce_mutation",
        "bool",
        "false",
        "Mutation exits 1 below mutation_min_score",
        "Gates",
    ),
    ConfigKeyDoc(
        "run_acceptance_in_check",
        "bool",
        "false",
        "Run acceptance scenarios inside `interlocks check`",
        "Gates",
    ),
    ConfigKeyDoc(
        "mutation_min_coverage",
        "float",
        "70.0",
        "Skip mutation when suite coverage below this",
        "Mutation",
    ),
    ConfigKeyDoc("mutation_max_runtime", "int", "600", "Seconds before SIGTERM", "Mutation"),
    ConfigKeyDoc(
        "mutation_min_score",
        "float",
        "80.0",
        "Kill ratio (%) enforced when blocking",
        "Mutation",
    ),
    ConfigKeyDoc(
        "mutation_ci_mode",
        "off|incremental|full",
        "off",
        "CI mutation strategy: off skips; "
        "incremental mutates only files changed vs mutation_since_ref; full runs all",
        "Mutation",
    ),
    ConfigKeyDoc(
        "mutation_since_ref",
        "str",
        "origin/main",
        "Base ref for incremental mutation",
        "Mutation",
    ),
    ConfigKeyDoc(
        "changed_ref",
        "str",
        "origin/main",
        "Base ref for `interlocks check --changed`",
        "Gates",
    ),
    ConfigKeyDoc(
        "acceptance_runner",
        "pytest-bdd|behave|off",
        "auto",
        "Gherkin runner (pytest-bdd default; behave auto-detected)",
        "Acceptance",
    ),
    ConfigKeyDoc(
        "require_acceptance",
        "bool",
        "false",
        "Fail stages when no Gherkin acceptance scenarios are present",
        "Acceptance",
    ),
    ConfigKeyDoc(
        "evaluate_dependency_freshness",
        "bool",
        "false",
        "Score dependency freshness policy in `interlocks evaluate`",
        "Dependencies",
    ),
    ConfigKeyDoc(
        "dependency_freshness_command",
        "str",
        "interlocks deps-freshness",
        "Focused command that checks outdated dependencies when run explicitly",
        "Dependencies",
    ),
    ConfigKeyDoc(
        "dependency_freshness_stage",
        "str",
        "interlocks nightly",
        "Stage that owns slower dependency freshness verification",
        "Dependencies",
    ),
    ConfigKeyDoc(
        "audit_severity_threshold",
        "low|medium|high|critical",
        "(none)",
        "Severity threshold used when evaluating high-severity audit policy",
        "Dependencies",
    ),
    ConfigKeyDoc(
        "pr_ci_runtime_budget_seconds",
        "int",
        "0",
        "Max acceptable `interlocks ci` runtime; 0 disables PR speed scoring",
        "Evidence",
    ),
    ConfigKeyDoc(
        "pr_ci_evidence_max_age_hours",
        "int",
        "24",
        "Max age for cached `interlocks ci` runtime evidence",
        "Evidence",
    ),
    ConfigKeyDoc(
        "ci_evidence_path",
        "str",
        ".interlocks/ci.json",
        "Local JSON timing evidence written by `interlocks ci`",
        "Evidence",
    ),
)


CONFIG_KEY_GROUP_ORDER: tuple[ConfigKeyGroup, ...] = (
    "Paths",
    "Runner",
    "Preset",
    "Thresholds",
    "Gates",
    "Mutation",
    "Acceptance",
    "Dependencies",
    "Evidence",
)


class InterlockUserError(Exception):
    """Base class for user-input errors surfaced at the CLI boundary.

    User-input errors print a clean message and exit 2 — they are not crashes
    and MUST NOT be captured by the crash reporter.
    """


class InterlockConfigError(InterlockUserError):
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


def _interlock_table(pyproject: dict[str, Any]) -> dict[str, Any]:
    table = pyproject.get("tool", {}).get("interlocks", {})
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


def _audit_severity_threshold_override(table: dict[str, Any]) -> AuditSeverityThreshold | None:
    value = table.get("audit_severity_threshold")
    if value in ("low", "medium", "high", "critical"):
        return value
    return None


@dataclass(frozen=True)
class InterlockConfig:
    project_root: Path
    src_dir: Path
    test_dir: Path
    test_runner: TestRunner
    test_invoker: TestInvoker
    preset: Preset | None = None
    pytest_args: tuple[str, ...] = ()
    # Thresholds — overridable via `[tool.interlocks]`. Single source of truth for
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
    enforce_behavior_attribution: bool = False
    run_mutation_in_ci: bool = False
    enforce_mutation: bool = False
    mutation_ci_mode: MutationCIMode = "off"
    mutation_since_ref: str = "origin/main"
    changed_ref: str = "origin/main"
    # Acceptance (Gherkin) — all optional; resolved lazily by the task.
    acceptance_runner: AcceptanceRunner | None = None
    features_dir: Path | None = None
    run_acceptance_in_check: bool = False
    require_acceptance: bool = False
    evaluate_dependency_freshness: bool = False
    dependency_freshness_command: str = "interlocks deps-freshness"
    dependency_freshness_stage: str = "interlocks nightly"
    audit_severity_threshold: AuditSeverityThreshold | None = None
    pr_ci_runtime_budget_seconds: int = 0
    pr_ci_evidence_max_age_hours: int = 24
    ci_evidence_path: Path = Path(".interlocks/ci.json")
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


COVERAGE_REQUIREMENT = "coverage>=7.13.5"


def python_command_prefix(cfg: InterlockConfig) -> list[str]:
    """Argv prefix for the target project's Python executable.

    ``uv`` projects execute through ``uv run python`` so project dependencies are
    active. Non-uv projects prefer an in-tree venv and only fall back to the
    current interpreter when no target venv exists.
    """
    if cfg.test_invoker == "uv":
        return ["uv", "run", "python"]
    venv_python = detect_target_interpreter(cfg.project_root)
    if venv_python is not None:
        return [str(venv_python)]
    return [sys.executable]


def invoker_prefix(cfg: InterlockConfig) -> list[str]:
    """Argv prefix for invoking a Python module in the target project."""
    return [*python_command_prefix(cfg), "-m"]


def coverage_invoker_prefix(cfg: InterlockConfig) -> list[str]:
    """Argv prefix for Coverage.py while preserving target-project dependencies."""
    if cfg.test_invoker == "uv":
        return ["uv", "run", "--with", COVERAGE_REQUIREMENT, "python", "-m"]
    return invoker_prefix(cfg)


def _runner_argv(cfg: InterlockConfig) -> list[str]:
    """Runner-specific argv tail — shared by the plain and coverage-wrapped commands."""
    if cfg.test_runner == "pytest":
        return ["pytest", cfg.test_dir_arg, "-q", *cfg.pytest_args]
    return ["unittest", "discover", "-s", cfg.test_dir_arg, "-q"]


def build_test_command(cfg: InterlockConfig) -> list[str]:
    """Build the full `interlocks test` command from ``cfg``."""
    return [*invoker_prefix(cfg), *_runner_argv(cfg)]


def build_coverage_test_command(
    cfg: InterlockConfig, *, coverage_args: tuple[str, ...] = ()
) -> list[str]:
    """Build ``coverage run [coverage_args] -m <runner> ...`` using the configured invoker."""
    return [
        *coverage_invoker_prefix(cfg),
        "coverage",
        "run",
        *coverage_args,
        "-m",
        *_runner_argv(cfg),
    ]


def load_config(start: Path | None = None) -> InterlockConfig:
    """Discover the project root and build a ``InterlockConfig``. Cached per project root."""
    return _load_config_cached(find_project_root(start))


def load_optional_config(start: Path | None = None) -> InterlockConfig | None:
    """Load config, returning ``None`` instead of raising on read/parse failure.

    Use at the CLI surface for read-only commands (``help``, ``presets``, ``config``)
    that should still render with bundled defaults when ``pyproject.toml`` is
    malformed or unreadable.
    """
    try:
        return load_config(start)
    except (OSError, tomllib.TOMLDecodeError):
        return None


def require_pyproject(cfg: InterlockConfig) -> None:
    """Raise ``InterlockConfigError`` when ``cfg.project_root`` has no ``pyproject.toml``.

    ``find_project_root`` falls back to CWD when no ancestor has a ``pyproject.toml`` —
    running gates against that bogus root produces confusing downstream errors. Call
    this at the CLI boundary to fail fast with an actionable message.
    """
    if not (cfg.project_root / "pyproject.toml").is_file():
        raise InterlockConfigError("no pyproject.toml — run `interlocks init` to scaffold")


@cache
def _load_config_cached(project_root: Path) -> InterlockConfig:
    pyproject = _load_pyproject(project_root)
    project_table = _interlock_table(pyproject)
    table, value_sources, preset, unsupported_presets = _resolve_config_table(project_table)

    test_dir_override = table.get("test_dir")
    src_dir_override = table.get("src_dir")
    features_dir_override = table.get("features_dir")
    runner_override = _runner_override(table)
    invoker_override = _invoker_override(table)
    acceptance_runner = _acceptance_runner_override(table)
    pytest_args = tuple(str(a) for a in (table.get("pytest_args") or ()))

    test_dir = _resolved_path(test_dir_override, detect_test_dir(project_root), project_root)
    src_dir = _resolved_path(
        src_dir_override, detect_src_dir(project_root, pyproject), project_root
    )
    features_dir = _resolved_path(
        features_dir_override, detect_features_dir(project_root, test_dir), project_root
    )
    test_runner: TestRunner = runner_override or detect_test_runner(
        project_root, pyproject, test_dir
    )
    test_invoker: TestInvoker = invoker_override or detect_test_invoker(project_root)
    run_acceptance_in_check, require_acceptance, mutation_ci_mode, mutation_since_ref = (
        _resolve_flags(table)
    )
    audit_severity_threshold = _audit_severity_threshold_override(table)
    thresholds = _threshold_overrides(table)
    if "enforce_behavior_attribution" not in thresholds:
        thresholds["enforce_behavior_attribution"] = _default_enforce_behavior_attribution(
            pyproject
        )
        if thresholds["enforce_behavior_attribution"]:
            value_sources.setdefault("enforce_behavior_attribution", _SOURCE_AUTO)
    dependency_freshness_command = _string_value(
        table, "dependency_freshness_command", InterlockConfig.dependency_freshness_command
    )
    dependency_freshness_stage = _string_value(
        table, "dependency_freshness_stage", InterlockConfig.dependency_freshness_stage
    )
    changed_ref = _string_value(table, "changed_ref", InterlockConfig.changed_ref)
    ci_evidence_path = _resolved_path(
        table.get("ci_evidence_path"),
        project_root / InterlockConfig.ci_evidence_path,
        project_root,
    )

    overrides = {
        "src_dir": src_dir_override,
        "test_dir": test_dir_override,
        "features_dir": features_dir_override,
        "test_runner": runner_override,
        "test_invoker": invoker_override,
        "acceptance_runner": acceptance_runner,
    }
    return InterlockConfig(
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
        require_acceptance=require_acceptance,
        mutation_ci_mode=mutation_ci_mode,
        mutation_since_ref=mutation_since_ref,
        changed_ref=changed_ref,
        dependency_freshness_command=dependency_freshness_command,
        dependency_freshness_stage=dependency_freshness_stage,
        audit_severity_threshold=audit_severity_threshold,
        ci_evidence_path=ci_evidence_path,
        value_sources=_complete_value_sources(value_sources, table, overrides=overrides),
        unsupported_presets=unsupported_presets,
        **thresholds,
    )


def _default_enforce_behavior_attribution(pyproject: dict[str, Any]) -> bool:
    project = pyproject.get("project")
    if not isinstance(project, dict) or project.get("name") != "interlocks":
        return False
    return any(behavior.public_symbol for behavior in INTERLOCKS_REGISTRY.behaviors)


def _resolved_path[T](override: object, fallback: T, project_root: Path) -> Path | T:
    """Resolve ``override`` against ``project_root`` when set; otherwise return ``fallback``."""
    if isinstance(override, str):
        return (project_root / override).resolve()
    return fallback


def _string_value(table: dict[str, Any], key: str, default: str) -> str:
    value = table.get(key)
    return value if isinstance(value, str) else default


def _resolve_flags(table: dict[str, Any]) -> tuple[bool, bool, MutationCIMode, str]:
    """Resolve (run_acceptance_in_check, require_acceptance, mutation_ci_mode, mutation_since)."""
    run_override = _coerce_bool(table.get("run_acceptance_in_check"))
    run_acceptance_in_check = (
        run_override if run_override is not None else InterlockConfig.run_acceptance_in_check
    )
    require_override = _coerce_bool(table.get("require_acceptance"))
    require_acceptance = (
        require_override if require_override is not None else InterlockConfig.require_acceptance
    )
    mutation_ci_mode = _mutation_ci_mode_override(table) or InterlockConfig.mutation_ci_mode
    since_ref_raw = table.get("mutation_since_ref")
    mutation_since_ref = (
        since_ref_raw if isinstance(since_ref_raw, str) else InterlockConfig.mutation_since_ref
    )
    return run_acceptance_in_check, require_acceptance, mutation_ci_mode, mutation_since_ref


_STRING_KEYS = (
    "src_dir",
    "test_dir",
    "mutation_since_ref",
    "changed_ref",
    "features_dir",
    "dependency_freshness_command",
    "dependency_freshness_stage",
    "ci_evidence_path",
)
_ENUM_PARSERS = {
    "test_runner": _runner_override,
    "test_invoker": _invoker_override,
    "acceptance_runner": _acceptance_runner_override,
    "mutation_ci_mode": _mutation_ci_mode_override,
    "audit_severity_threshold": _audit_severity_threshold_override,
}


def _resolve_config_table(
    project_table: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str], Preset | None, tuple[str, ...]]:
    """Resolve config using preset defaults before explicit project values."""
    resolved: dict[str, Any] = {}
    sources: dict[str, str] = {}
    active_preset: Preset | None = None
    unsupported: list[str] = []

    preset = _preset_override(project_table)
    if preset is not None:
        resolved.update(_PRESET_DEFAULTS[preset])
        sources.update(dict.fromkeys(_PRESET_DEFAULTS[preset], _SOURCE_PRESET))
        resolved["preset"] = preset
        sources["preset"] = _SOURCE_PROJECT
        active_preset = preset
    elif isinstance(project_table.get("preset"), str):
        unsupported.append(f"{_SOURCE_PROJECT}: {project_table['preset']}")

    explicit = _explicit_config_overrides(project_table)
    resolved.update(explicit)
    sources.update(dict.fromkeys(explicit, _SOURCE_PROJECT))

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
    value = _coerce_bool(table.get("require_acceptance"))
    if value is not None:
        overrides["require_acceptance"] = value
    return overrides


def _complete_value_sources(
    sources: dict[str, str],
    table: dict[str, Any],
    *,
    overrides: dict[str, object],
) -> dict[str, str]:
    complete = dict(sources)
    default_keys = (
        *_INT_THRESHOLDS,
        *_FLOAT_THRESHOLDS,
        *_BOOL_THRESHOLDS,
        "mutation_ci_mode",
        "mutation_since_ref",
        "changed_ref",
        "run_acceptance_in_check",
        "require_acceptance",
        "evaluate_dependency_freshness",
        "dependency_freshness_command",
        "dependency_freshness_stage",
        "audit_severity_threshold",
        "pr_ci_runtime_budget_seconds",
        "pr_ci_evidence_max_age_hours",
        "ci_evidence_path",
    )
    for key in default_keys:
        complete.setdefault(key, _SOURCE_DEFAULT)
    for key, value in overrides.items():
        if value is None:
            complete[key] = _SOURCE_AUTO
        else:
            complete.setdefault(key, _SOURCE_PROJECT)
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
    "pr_ci_runtime_budget_seconds",
    "pr_ci_evidence_max_age_hours",
)
_FLOAT_THRESHOLDS = ("crap_max", "mutation_min_coverage", "mutation_min_score")
_BOOL_THRESHOLDS = (
    "enforce_crap",
    "enforce_behavior_attribution",
    "run_mutation_in_ci",
    "enforce_mutation",
    "evaluate_dependency_freshness",
)


def _threshold_overrides(table: dict[str, Any]) -> dict[str, Any]:
    """Parse known threshold keys from ``[tool.interlocks]`` with type coercion.

    Invalid values (non-numeric, wrong type) fall through silently — the
    dataclass default applies. Keeps config parsing permissive.
    """
    overrides: dict[str, Any] = {}
    for key in _INT_THRESHOLDS:
        value = _coerce_int(table.get(key))
        if value is not None:
            overrides[key] = value
    for key in _FLOAT_THRESHOLDS:
        value = coerce_float(table.get(key))
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


def coerce_float(raw: object) -> float | None:
    """Coerce ``raw`` to float when it is a number; return ``None`` for booleans/non-numbers."""
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
