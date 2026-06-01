"""Property tests for `interlocks config` display helpers."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given
from hypothesis import strategies as st

from interlocks.config import SKIP_LABELS, InterlockConfig
from interlocks.defaults_path import TOOL_CONFIG_SPECS, ToolConfigSource
from interlocks.tasks.config import (
    CONFIG_KEYS,
    _config_usage,
    _config_usage_payload,
    _current_label,
    _display_current_label,
    _display_source_label,
    _json_value,
    _key_widths,
    _resolved_value,
    _source_label,
    _tool_source_rows,
    _tool_specific_note,
)

_REL_PATH = st.from_regex(r"[a-z][a-z0-9_/-]{0,30}", fullmatch=True).filter(
    lambda value: "//" not in value and not value.endswith("/")
)
_TOOL_NAME = st.from_regex(r"[a-z][a-z0-9_-]{0,20}", fullmatch=True)
_KNOWN_TOOL = st.sampled_from(sorted(TOOL_CONFIG_SPECS))
_FLAG = st.from_regex(r"--[a-z][a-z0-9-]{0,20}", fullmatch=True)


def _cfg(root: Path, *, properties_dir: Path | None = None) -> InterlockConfig:
    return InterlockConfig(
        project_root=root,
        src_dir=root / "src",
        test_dir=root / "tests",
        test_runner="pytest",
        test_invoker="python",
        features_dir=root / "tests" / "features",
        properties_dir=properties_dir,
    )


@given(tool=_KNOWN_TOOL)
def test_config_usage_payload_lists_known_tools(tool: str) -> None:
    payload = _config_usage_payload()

    assert payload["command"] == "config"
    assert payload["error"] == "invalid usage"
    assert payload["usage"] == _config_usage()
    assert payload["expected_tools"] == list(TOOL_CONFIG_SPECS)
    assert tool in str(payload["usage"])


@given(_REL_PATH)
def test_resolved_properties_dir_uses_project_relative_label(relpath: str) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        cfg = _cfg(root, properties_dir=root / relpath)

        assert _resolved_value(cfg, "properties_dir") == relpath
        assert _current_label(cfg, "properties_dir") == relpath


@given(st.lists(st.sampled_from(sorted(SKIP_LABELS)), unique=True, max_size=8))
def test_current_label_formats_skip_set_in_sorted_order(labels: list[str]) -> None:
    with TemporaryDirectory() as raw_root:
        cfg = replace(_cfg(Path(raw_root)), skip=frozenset(labels))

        assert _current_label(cfg, "skip") == "[" + ", ".join(sorted(labels)) + "]"
        assert _json_value(cfg, "skip") == sorted(labels)


@given(st.lists(st.text(max_size=12), max_size=8))
def test_current_label_formats_pytest_args_as_list(args: list[str]) -> None:
    with TemporaryDirectory() as raw_root:
        cfg = replace(_cfg(Path(raw_root)), pytest_args=tuple(args))

        assert _current_label(cfg, "pytest_args") == "[" + ", ".join(args) + "]"
        assert _json_value(cfg, "pytest_args") == args


@given(key=_TOOL_NAME, source=st.text(min_size=1, max_size=30))
def test_source_label_uses_value_sources_or_unknown(key: str, source: str) -> None:
    with TemporaryDirectory() as raw_root:
        cfg = replace(_cfg(Path(raw_root)), value_sources={key: source})

        assert _source_label(cfg, key) == source
        assert _source_label(cfg, f"{key}_missing") == "unknown"
        assert _source_label(None, key) == "unreadable"


@given(skip_labels=st.lists(st.sampled_from(sorted(SKIP_LABELS)), unique=True, max_size=8))
def test_key_widths_cover_all_rendered_config_columns(skip_labels: list[str]) -> None:
    with TemporaryDirectory() as raw_root:
        cfg = replace(_cfg(Path(raw_root)), skip=frozenset(skip_labels))

        widths = _key_widths(cfg)

    assert widths.name >= max(len(key.name) for key in CONFIG_KEYS)
    assert widths.type >= max(len(key.type) for key in CONFIG_KEYS)
    assert widths.default >= max(len(key.default) for key in CONFIG_KEYS)
    assert widths.current >= max(len(_current_label(cfg, key.name)) for key in CONFIG_KEYS)
    assert widths.source >= max(len(_source_label(cfg, key.name)) for key in CONFIG_KEYS)


def test_missing_config_display_labels_do_not_claim_resolved_defaults() -> None:
    assert _display_current_label(None, "coverage_min", state="missing") == "(not resolved)"
    assert _display_source_label(None, "coverage_min", state="missing") == "missing-project"
    assert _display_current_label(None, "coverage_min", state="unreadable") == "(unreadable)"
    assert _display_source_label(None, "coverage_min", state="unreadable") == "unreadable"


@given(
    tool=_TOOL_NAME,
    source_label=st.text(min_size=1, max_size=30).filter(lambda value: value != "bundled"),
    bundled_only=st.booleans(),
    flag=_FLAG,
)
def test_tool_source_rows_switch_between_project_and_bundled_source(
    tool: str,
    source_label: str,
    bundled_only: bool,
    flag: str,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        cfg = _cfg(root)
        project_path = root / "pyproject.toml"
        bundled_path = root / "defaults" / "tool.toml"
        source = ToolConfigSource(
            tool=tool,
            source=source_label,
            path=project_path,
            bundled_path=bundled_path,
            flag=flag,
        )

        rows = dict(_tool_source_rows(cfg, source, bundled_only=bundled_only))

    assert rows["tool"] == tool
    assert rows["bundled_path"] == "defaults/tool.toml"
    if bundled_only:
        assert rows["source"] == "bundled"
        assert rows["path"] == "defaults/tool.toml"
        assert rows["flag"] == f"{flag} defaults/tool.toml"
    else:
        assert rows["source"] == source_label
        assert rows["path"] == "pyproject.toml"
        assert rows["flag"] == "(none; native project config detected)"


@given(tool=_TOOL_NAME, flag=_FLAG)
def test_tool_source_rows_include_flag_for_bundled_source(tool: str, flag: str) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        cfg = _cfg(root)
        bundled_path = root / "defaults" / "tool.toml"
        source = ToolConfigSource(
            tool=tool,
            source="bundled",
            path=bundled_path,
            bundled_path=bundled_path,
            flag=flag,
        )

        rows = dict(_tool_source_rows(cfg, source, bundled_only=False))

    assert rows["source"] == "bundled"
    assert rows["path"] == "defaults/tool.toml"
    assert rows["flag"] == f"{flag} defaults/tool.toml"


@given(tool=_KNOWN_TOOL, bundled_only=st.booleans(), source_is_bundled=st.booleans())
def test_tool_specific_note_only_explains_bundled_basedpyright(
    tool: str,
    bundled_only: bool,
    source_is_bundled: bool,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        spec = TOOL_CONFIG_SPECS[tool]
        source = ToolConfigSource(
            tool=tool,
            source="bundled" if source_is_bundled else "project: pyproject.toml",
            path=root / "pyproject.toml",
            bundled_path=root / spec.filename,
            flag=spec.flag,
        )

        note = _tool_specific_note(source, bundled_only=bundled_only)

    should_note = tool == "basedpyright" and (source_is_bundled or bundled_only)
    assert (note is not None) is should_note
    if note is not None:
        assert "[tool.basedpyright]" in note
        assert "pyrightconfig.json" in note
