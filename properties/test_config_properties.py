"""Property tests for configuration parsing helpers."""

from __future__ import annotations

import math
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

from hypothesis import given
from hypothesis import strategies as st

from interlocks.behavior_coverage import INTERLOCKS_REGISTRY
from interlocks.config import (
    _BOOL_THRESHOLDS,
    _FLOAT_THRESHOLDS,
    _INT_THRESHOLDS,
    _PRESET_DEFAULTS,
    _SOURCE_PRESET,
    _SOURCE_PROJECT,
    _SUPPORTED_PRESETS,
    InterlockConfig,
    Preset,
    TestInvoker,
    _arch_layers_override,
    _coerce_bool,
    _complete_value_sources,
    _default_enforce_behavior_attribution,
    _enum_override,
    _explicit_config_overrides,
    _interlock_table,
    _preset_override,
    _resolve_config_table,
    _threshold_overrides,
    _tool_version_overrides,
    coerce_float,
    coerce_int,
    project_env_ready,
)
from interlocks.defaults.tools import DEFAULTS as TOOL_DEFAULTS
from interlocks.detect import expected_target_interpreter
from interlocks.skip import SKIP_LABELS

_NON_NUMBERS = st.one_of(st.none(), st.booleans(), st.text(), st.lists(st.integers()))
_BOOLEAN_CHECK_KEYS = st.sampled_from([
    "run_acceptance_in_check",
    "run_properties_in_check",
    "require_acceptance",
])
_STRING_CONFIG_KEYS = st.sampled_from([
    "src_dir",
    "test_dir",
    "features_dir",
    "properties_dir",
    "mutation_since_ref",
    "changed_ref",
    "dependency_freshness_command",
    "dependency_freshness_stage",
    "ci_evidence_path",
])
_TOOL_TABLE_VALUES = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-10, max_value=10),
    st.sampled_from(["", " ", "\t", "\n", " 1.2.3 ", ">=1.0 "]),
    st.text(max_size=20),
    st.lists(st.text(max_size=5), max_size=3),
)
_TOOL_TABLE_KEYS = st.sampled_from([*TOOL_DEFAULTS.keys(), "unknown-tool", "ruff-extra"])
_ARCH_LAYER_VALUES = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-10, max_value=10),
    st.text(max_size=20),
)
_VALUE_SOURCE_KEYS = st.sampled_from([
    "coverage_min",
    "crap_max",
    "mutation_ci_mode",
    "src_dir",
    "test_dir",
    "features_dir",
    "properties_dir",
    "acceptance_runner",
])
_OVERRIDE_SOURCE_KEYS = st.sampled_from([
    "src_dir",
    "test_dir",
    "features_dir",
    "properties_dir",
    "test_runner",
    "test_invoker",
    "acceptance_runner",
])
_VALUE_SOURCE_VALUES = st.sampled_from([
    "project-configured",
    "preset-derived",
    "auto-detected",
    "bundled-default",
    "baseline-floor",
])
_EXPLICIT_VALUE = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-100, max_value=100),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=30),
    st.lists(st.text(max_size=10), max_size=5),
)
_THRESHOLD_KEY = st.sampled_from([*_INT_THRESHOLDS, *_FLOAT_THRESHOLDS, *_BOOL_THRESHOLDS])
_ENUM_KEY_VALUES = st.sampled_from([
    ("test_runner", ("pytest", "unittest")),
    ("test_invoker", ("python", "uv")),
    ("acceptance_runner", ("pytest-bdd", "behave", "off")),
    ("mutation_ci_mode", ("off", "incremental", "full")),
    ("audit_severity_threshold", ("low", "medium", "high", "critical")),
    ("arch_template", ("default", "layered")),
])
_DEFAULT_VALUE_SOURCE_KEYS = frozenset({
    *_INT_THRESHOLDS,
    *_FLOAT_THRESHOLDS,
    *_BOOL_THRESHOLDS,
    "mutation_ci_mode",
    "mutation_since_ref",
    "changed_ref",
    "skip",
    "run_acceptance_in_check",
    "run_properties_in_check",
    "require_acceptance",
    "evaluate_dependency_freshness",
    "dependency_freshness_command",
    "dependency_freshness_stage",
    "audit_severity_threshold",
    "arch_template",
    "arch_layers",
    "pr_ci_runtime_budget_seconds",
    "pr_ci_evidence_max_age_hours",
    "ci_evidence_path",
    "pytest_args",
    "preset",
})


@given(
    tool=st.one_of(
        st.none(),
        st.text(max_size=20),
        st.integers(min_value=-10, max_value=10),
        st.booleans(),
        st.dictionaries(
            st.text(max_size=12),
            st.one_of(st.text(max_size=20), st.integers(), st.booleans()),
            max_size=5,
        ),
    )
)
def test_interlock_table_returns_only_real_interlocks_tables(tool: object) -> None:
    pyproject = {"tool": tool}

    table = _interlock_table(pyproject)

    if isinstance(tool, dict) and isinstance(tool.get("interlocks"), dict):
        assert table == tool["interlocks"]
    else:
        assert table == {}


@given(
    table=st.dictionaries(
        st.text(max_size=12),
        st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=20)),
        max_size=8,
    )
)
def test_interlock_table_returns_project_table_without_copying(table: dict[str, object]) -> None:
    pyproject = {"tool": {"interlocks": table}}

    assert _interlock_table(pyproject) is table


@given(_NON_NUMBERS)
def test_numeric_coercion_rejects_non_numbers(raw: object) -> None:
    assert coerce_int(raw) is None
    assert coerce_float(raw) is None


@given(st.integers())
def test_integer_threshold_coercion_preserves_integers(value: int) -> None:
    assert coerce_int(value) == value
    assert coerce_float(value) == float(value)


@given(st.floats(allow_nan=False, allow_infinity=False))
def test_float_threshold_coercion_accepts_finite_floats(value: float) -> None:
    assert coerce_int(value) == int(value)
    assert coerce_float(value) == value


@given(st.sampled_from([math.inf, -math.inf, math.nan]))
def test_threshold_coercion_rejects_non_finite_floats(value: float) -> None:
    assert coerce_int(value) is None
    assert coerce_float(value) is None


@given(st.sampled_from(_SUPPORTED_PRESETS))
def test_config_table_supported_preset_seeds_defaults(preset: str) -> None:
    selected = cast("Preset", preset)
    resolved, sources, active_preset, unsupported = _resolve_config_table({"preset": preset})

    expected = dict(_PRESET_DEFAULTS[selected])
    expected["preset"] = preset
    assert resolved == expected
    assert active_preset == preset
    assert unsupported == ()
    assert sources["preset"] == _SOURCE_PROJECT
    assert all(sources[key] == _SOURCE_PRESET for key in _PRESET_DEFAULTS[selected])


@given(preset=st.one_of(st.sampled_from(_SUPPORTED_PRESETS), st.text(max_size=30), st.integers()))
def test_preset_override_accepts_only_supported_presets(preset: object) -> None:
    parsed = _preset_override({"preset": preset})

    assert parsed == (preset if preset in _SUPPORTED_PRESETS else None)


@given(table=st.dictionaries(st.text(max_size=20), _EXPLICIT_VALUE, max_size=6))
def test_preset_override_returns_none_when_preset_key_is_absent(table: dict[str, object]) -> None:
    table.pop("preset", None)

    assert _preset_override(table) is None


@given(row=_ENUM_KEY_VALUES, value=st.one_of(st.text(max_size=30), st.integers(), st.booleans()))
def test_enum_override_accepts_only_known_values(
    row: tuple[str, tuple[str, ...]], value: object
) -> None:
    key, options = row

    parsed = _enum_override({key: value}, key)

    assert parsed == (value if value in options else None)


@given(
    row=_ENUM_KEY_VALUES, table=st.dictionaries(st.text(max_size=20), _EXPLICIT_VALUE, max_size=6)
)
def test_enum_override_returns_none_when_key_is_absent(
    row: tuple[str, tuple[str, ...]],
    table: dict[str, object],
) -> None:
    key, _options = row
    table.pop(key, None)

    assert _enum_override(table, key) is None


@given(raw=st.one_of(st.booleans(), st.none(), st.integers(), st.text(max_size=20)))
def test_coerce_bool_accepts_only_boolean_values(raw: object) -> None:
    parsed = _coerce_bool(raw)

    assert parsed == (raw if isinstance(raw, bool) else None)


@given(raw=st.one_of(st.integers(), st.floats(allow_nan=False), st.text(max_size=20), st.none()))
def test_coerce_bool_does_not_treat_truthy_or_falsy_non_bools_as_bool(raw: object) -> None:
    assert _coerce_bool(raw) is None


@given(st.text(max_size=30).filter(lambda value: value not in _SUPPORTED_PRESETS))
def test_config_table_reports_unsupported_preset_strings(preset: str) -> None:
    resolved, sources, active_preset, unsupported = _resolve_config_table({"preset": preset})

    assert resolved == {}
    assert sources == {}
    assert active_preset is None
    assert unsupported == (f"{_SOURCE_PROJECT}: {preset}",)


@given(st.one_of(st.none(), st.booleans(), st.integers(), st.lists(st.text(), max_size=3)))
def test_config_table_ignores_non_string_preset_values(preset: object) -> None:
    resolved, sources, active_preset, unsupported = _resolve_config_table({"preset": preset})

    assert resolved == {}
    assert sources == {}
    assert active_preset is None
    assert unsupported == ()


@given(
    preset=st.sampled_from(_SUPPORTED_PRESETS),
    key=_BOOLEAN_CHECK_KEYS,
    value=st.booleans(),
)
def test_config_table_project_booleans_override_preset_defaults(
    preset: str,
    key: str,
    value: bool,
) -> None:
    resolved, sources, active_preset, unsupported = _resolve_config_table({
        "preset": preset,
        key: value,
    })

    assert active_preset == preset
    assert unsupported == ()
    assert resolved[key] is value
    assert sources[key] == _SOURCE_PROJECT


@given(
    key=_STRING_CONFIG_KEYS,
    value=st.text(max_size=60),
    preset=st.one_of(st.none(), st.sampled_from(_SUPPORTED_PRESETS)),
)
def test_config_table_project_strings_are_explicit_overrides(
    key: str,
    value: str,
    preset: str | None,
) -> None:
    table: dict[str, Any] = {key: value}
    if preset is not None:
        table["preset"] = preset

    resolved, sources, _active_preset, unsupported = _resolve_config_table(table)

    assert unsupported == ()
    assert resolved[key] == value
    assert sources[key] == _SOURCE_PROJECT


@given(st.dictionaries(keys=_TOOL_TABLE_KEYS, values=_TOOL_TABLE_VALUES, max_size=20))
def test_tool_version_overrides_keep_known_nonblank_string_pins(
    tools: dict[str, object],
) -> None:
    table: dict[str, Any] = {"tools": tools}

    assert _tool_version_overrides(table) == {
        name: value.strip()
        for name, value in tools.items()
        if name in TOOL_DEFAULTS and isinstance(value, str) and value.strip()
    }


@given(st.one_of(_TOOL_TABLE_VALUES, st.lists(_TOOL_TABLE_VALUES, max_size=3)))
def test_tool_version_overrides_ignore_non_tables(raw: object) -> None:
    assert _tool_version_overrides({"tools": raw}) == {}


@given(tool=st.sampled_from(tuple(TOOL_DEFAULTS)), raw_pin=st.text(max_size=20))
def test_tool_version_overrides_strips_known_tool_pins(tool: str, raw_pin: str) -> None:
    parsed = _tool_version_overrides({"tools": {tool: f"  {raw_pin}  "}})

    assert parsed == ({tool: raw_pin.strip()} if raw_pin.strip() else {})


@given(
    tool=st.sampled_from(tuple(TOOL_DEFAULTS)),
    override=st.one_of(st.none(), st.text(min_size=1, max_size=20)),
)
def test_interlock_config_tool_version_prefers_override_then_default(
    tool: str,
    override: str | None,
) -> None:
    cfg = InterlockConfig(
        project_root=Path(),
        src_dir=Path("interlocks"),
        test_dir=Path("tests"),
        test_runner="pytest",
        test_invoker="python",
        tool_versions={tool: override} if override is not None else {},
    )

    expected = override if override is not None else TOOL_DEFAULTS[tool]
    assert cfg.tool_version(tool) == expected
    assert InterlockConfig.tool_version(cfg, tool) == expected


@given(invoker=st.sampled_from(["python", "uv"]), has_venv=st.booleans())
def test_project_env_ready_matches_invoker_and_in_tree_venv(
    invoker: str,
    has_venv: bool,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        if has_venv:
            interpreter = expected_target_interpreter(root)
            interpreter.parent.mkdir(parents=True)
            interpreter.write_text("", encoding="utf-8")
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "interlocks",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker=cast("TestInvoker", invoker),
        )

        ready = project_env_ready(cfg)

    assert ready is (invoker == "uv" or has_venv)


@given(has_venv=st.booleans())
def test_project_env_ready_uv_invoker_ignores_venv_presence(has_venv: bool) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        if has_venv:
            interpreter = expected_target_interpreter(root)
            interpreter.parent.mkdir(parents=True)
            interpreter.write_text("", encoding="utf-8")
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "interlocks",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="uv",
        )

        assert project_env_ready(cfg) is True


@given(st.lists(_ARCH_LAYER_VALUES, max_size=20))
def test_arch_layers_override_keeps_ordered_nonblank_strings(layers: list[object]) -> None:
    table: dict[str, Any] = {"arch_layers": {"layers": layers}}

    assert _arch_layers_override(table) == tuple(
        item.strip() for item in layers if isinstance(item, str) and item.strip()
    )


@given(st.one_of(_ARCH_LAYER_VALUES, st.dictionaries(st.text(), _ARCH_LAYER_VALUES, max_size=3)))
def test_arch_layers_override_ignores_missing_or_malformed_layers(raw: object) -> None:
    table: dict[str, Any] = {"arch_layers": raw}
    if isinstance(raw, dict) and isinstance(raw.get("layers"), list):
        return

    assert _arch_layers_override(table) == ()


@given(layers=st.lists(st.text(max_size=20), max_size=10))
def test_arch_layers_override_drops_blank_layers_without_reordering(layers: list[str]) -> None:
    parsed = _arch_layers_override({"arch_layers": {"layers": [f" {layer} " for layer in layers]}})

    assert parsed == tuple(layer.strip() for layer in layers if layer.strip())


@given(key=_STRING_CONFIG_KEYS, value=_EXPLICIT_VALUE)
def test_explicit_config_overrides_only_keep_string_pathlike_values(
    key: str, value: object
) -> None:
    overrides = _explicit_config_overrides({key: value})

    if isinstance(value, str):
        assert overrides[key] == value
    else:
        assert key not in overrides


@given(
    args=st.one_of(
        st.lists(st.one_of(st.text(max_size=20), st.integers(), st.booleans()), max_size=6),
        st.text(max_size=20),
        st.integers(),
        st.none(),
    )
)
def test_explicit_config_overrides_only_keep_pytest_args_lists(args: object) -> None:
    overrides = _explicit_config_overrides({"pytest_args": args})

    if isinstance(args, list):
        assert overrides["pytest_args"] == args
    else:
        assert "pytest_args" not in overrides


@given(labels=st.lists(st.sampled_from(sorted(SKIP_LABELS)), max_size=12))
def test_explicit_config_overrides_normalizes_skip_labels(labels: list[str]) -> None:
    noisy = [f"  {label.upper()}  " for label in labels]
    overrides = _explicit_config_overrides({"skip": noisy})

    assert overrides["skip"] == tuple(dict.fromkeys(label.lower() for label in labels))


@given(key=_THRESHOLD_KEY, value=_EXPLICIT_VALUE)
def test_threshold_overrides_match_key_specific_coercion(key: str, value: object) -> None:
    overrides = _threshold_overrides({key: value})

    if key in _INT_THRESHOLDS:
        expected = coerce_int(value)
    elif key in _FLOAT_THRESHOLDS:
        expected = coerce_float(value)
    else:
        expected = value if isinstance(value, bool) else None
    if expected is None:
        assert key not in overrides
    else:
        assert overrides[key] == expected


@given(table=st.dictionaries(st.text(max_size=20), _EXPLICIT_VALUE, max_size=20))
def test_threshold_overrides_outputs_only_known_threshold_keys(table: dict[str, object]) -> None:
    overrides = _threshold_overrides(table)

    assert set(overrides) <= {*_INT_THRESHOLDS, *_FLOAT_THRESHOLDS, *_BOOL_THRESHOLDS}
    assert all(value is not None for value in overrides.values())


@given(project_name=st.one_of(st.none(), st.text(max_size=30), st.integers(), st.booleans()))
def test_default_behavior_attribution_only_auto_enforces_for_interlocks_project(
    project_name: object,
) -> None:
    pyproject = {"project": {"name": project_name}}
    has_public_symbols = any(behavior.public_symbol for behavior in INTERLOCKS_REGISTRY.behaviors)

    assert _default_enforce_behavior_attribution(pyproject) is (
        project_name == "interlocks" and has_public_symbols
    )


@given(
    st.one_of(
        st.none(),
        st.text(max_size=30),
        st.integers(),
        st.booleans(),
        st.lists(st.text()),
    )
)
def test_default_behavior_attribution_ignores_malformed_project_tables(project: object) -> None:
    assert _default_enforce_behavior_attribution({"project": project}) is False


@given(
    sources=st.dictionaries(_VALUE_SOURCE_KEYS, _VALUE_SOURCE_VALUES, max_size=10),
    overrides=st.dictionaries(
        _OVERRIDE_SOURCE_KEYS,
        st.one_of(st.none(), st.text(max_size=20), st.integers(min_value=-5, max_value=5)),
        max_size=10,
    ),
    preset=st.one_of(st.none(), st.text(max_size=20)),
)
def test_complete_value_sources_preserves_and_fills_sources(
    sources: dict[str, str],
    overrides: dict[str, object],
    preset: str | None,
) -> None:
    table = {} if preset is None else {"preset": preset}

    complete = _complete_value_sources(sources, table, overrides=overrides)

    for key, source in sources.items():
        if overrides.get(key, object()) is None:
            assert complete[key] == "auto-detected"
        else:
            assert complete[key] == source
    for key, value in overrides.items():
        if value is None:
            assert complete[key] == "auto-detected"
        elif key not in sources:
            assert complete[key] == "project-configured"
    assert complete["preset"] == ("bundled-default" if preset is None else "project-configured")


@given(
    sources=st.dictionaries(_VALUE_SOURCE_KEYS, _VALUE_SOURCE_VALUES, max_size=10),
    overrides=st.dictionaries(_OVERRIDE_SOURCE_KEYS, _EXPLICIT_VALUE, max_size=10),
    preset=st.one_of(st.none(), st.text(max_size=20)),
)
def test_complete_value_sources_covers_all_default_and_override_keys(
    sources: dict[str, str],
    overrides: dict[str, object],
    preset: str | None,
) -> None:
    table = {} if preset is None else {"preset": preset}

    complete = _complete_value_sources(sources, table, overrides=overrides)

    assert _DEFAULT_VALUE_SOURCE_KEYS <= complete.keys()
    assert sources.keys() <= complete.keys()
    assert overrides.keys() <= complete.keys()


@given(
    sources=st.dictionaries(_VALUE_SOURCE_KEYS, _VALUE_SOURCE_VALUES, max_size=10),
    table=st.dictionaries(_VALUE_SOURCE_KEYS, _EXPLICIT_VALUE, max_size=10),
    overrides=st.dictionaries(_OVERRIDE_SOURCE_KEYS, _EXPLICIT_VALUE, max_size=10),
)
def test_complete_value_sources_does_not_mutate_inputs(
    sources: dict[str, str],
    table: dict[str, object],
    overrides: dict[str, object],
) -> None:
    original_sources = dict(sources)
    original_table = dict(table)
    original_overrides = dict(overrides)

    complete = _complete_value_sources(sources, table, overrides=overrides)

    assert complete is not sources
    assert sources == original_sources
    assert table == original_table
    assert overrides == original_overrides
