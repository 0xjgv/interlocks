"""Property tests for bundled/default config source detection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, cast

from hypothesis import given
from hypothesis import strategies as st

from interlocks.defaults_path import (
    TOOL_CONFIG_SPECS,
    ToolConfigSpec,
    config_flag_if_absent,
    path,
    project_config_source,
    tool_config_source,
)

if TYPE_CHECKING:
    from interlocks.config import InterlockConfig

_SECTION = st.from_regex(r"[A-Za-z][A-Za-z0-9_-]{0,20}", fullmatch=True)
_SIDECAR = st.from_regex(r"[A-Za-z0-9_.-]{1,24}", fullmatch=True).filter(
    lambda value: "/" not in value and value not in {".", ".."}
)
_KNOWN_TOOL = st.sampled_from(tuple(TOOL_CONFIG_SPECS))
_KNOWN_SPEC = st.sampled_from(tuple(TOOL_CONFIG_SPECS.values()))


@dataclass(frozen=True)
class _Cfg:
    project_root: Path
    pyproject: dict[str, object]


@given(section=_SECTION, sidecars=st.lists(_SIDECAR, max_size=5, unique=True))
def test_project_config_source_prefers_pyproject_tool_section(
    section: str, sidecars: list[str]
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        for name in sidecars:
            (root / name).write_text("", encoding="utf-8")
        cfg = _Cfg(root, {"tool": {section: {}}})

        assert project_config_source(cast("InterlockConfig", cfg), section, sidecars) == (
            f"pyproject.toml [tool.{section}]",
            root / "pyproject.toml",
        )


@given(
    section=_SECTION,
    sidecars=st.lists(_SIDECAR, min_size=1, max_size=5, unique=True),
    existing_index=st.integers(min_value=0, max_value=4),
)
def test_project_config_source_uses_first_existing_sidecar(
    section: str, sidecars: list[str], existing_index: int
) -> None:
    index = existing_index % len(sidecars)
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        for name in sidecars[index:]:
            (root / name).write_text("", encoding="utf-8")
        cfg = _Cfg(root, {"tool": {}})

        assert project_config_source(cast("InterlockConfig", cfg), section, sidecars) == (
            sidecars[index],
            root / sidecars[index],
        )


@given(section=_SECTION, sidecars=st.lists(_SIDECAR, max_size=5, unique=True))
def test_project_config_source_returns_none_when_absent(section: str, sidecars: list[str]) -> None:
    with TemporaryDirectory() as raw_root:
        cfg = _Cfg(Path(raw_root), {"tool": {}})

        assert project_config_source(cast("InterlockConfig", cfg), section, sidecars) is None


@given(tool=_KNOWN_TOOL)
def test_tool_config_source_returns_bundled_source_when_project_has_no_override(tool: str) -> None:
    with TemporaryDirectory() as raw_root:
        cfg = _Cfg(Path(raw_root), {"tool": {}})

        source = tool_config_source(cast("InterlockConfig", cfg), tool)

    spec = TOOL_CONFIG_SPECS[tool]
    assert source.tool == tool
    assert source.source == "bundled"
    assert source.path == path(spec.filename)
    assert source.bundled_path == source.path
    assert source.flag == spec.flag
    assert source.is_bundled is True


@given(spec=_KNOWN_SPEC, owns_pyproject_section=st.booleans())
def test_config_flag_if_absent_returns_bundled_flag_only_without_project_config(
    spec: ToolConfigSpec,
    owns_pyproject_section: bool,
) -> None:
    with TemporaryDirectory() as raw_root:
        cfg = _Cfg(Path(raw_root), {"tool": {spec.section: {}} if owns_pyproject_section else {}})

        flags = config_flag_if_absent(
            cast("InterlockConfig", cfg),
            section=spec.section,
            filename=spec.filename,
            flag=spec.flag,
            sidecars=spec.sidecars,
        )

    expected = [] if owns_pyproject_section else [spec.flag, str(path(spec.filename))]
    assert flags == expected
