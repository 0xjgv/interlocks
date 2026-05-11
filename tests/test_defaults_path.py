"""Tests for `interlocks.defaults_path` — bundled config resolution + project detection."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from interlocks.config import load_config
from interlocks.defaults_path import has_project_config, path, tool_config_source


def _write(file_path: Path, text: str) -> None:
    file_path.write_text(textwrap.dedent(text), encoding="utf-8")


def test_path_resolves_bundled_init() -> None:
    """The defaults package always ships at least `__init__.py`."""
    resolved = path("__init__.py")
    assert resolved.is_file()
    assert resolved.name == "__init__.py"


def test_path_missing_resource_is_not_a_file() -> None:
    """Unknown names don't raise — they just fail the is_file check."""
    assert not path("does-not-exist.toml").is_file()


def test_bundled_pyrightconfig_preserves_adoption_policy() -> None:
    config = json.loads(path("pyrightconfig.json").read_text(encoding="utf-8"))

    assert config["typeCheckingMode"] == "standard"
    assert config["reportDeprecated"] == "error"
    for diagnostic in (
        "reportUnusedCallResult",
        "reportMissingTypeStubs",
        "reportUnknownVariableType",
        "reportUnknownMemberType",
        "reportUnknownArgumentType",
        "reportAny",
    ):
        assert config[diagnostic] is False


_BARE = "[project]\nname='probe'\nversion='0.0.0'\n"

# ─────────────── has_project_config ─────────────────────────────────


def test_has_project_config_detects_tool_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "probe"
        version = "0.0.0"

        [tool.ruff]
        line-length = 99
        """,
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert has_project_config(cfg, "ruff") is True


def test_has_project_config_detects_sidecar_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "pyproject.toml", _BARE)
    (tmp_path / "ruff.toml").write_text("line-length = 99\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert has_project_config(cfg, "ruff", sidecars=("ruff.toml", ".ruff.toml")) is True


def test_has_project_config_returns_false_when_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "pyproject.toml", _BARE)
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert has_project_config(cfg, "ruff", sidecars=("ruff.toml",)) is False


def test_tool_config_source_reports_bundled_when_project_config_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "pyproject.toml", _BARE)
    monkeypatch.chdir(tmp_path)

    cfg = load_config()
    source = tool_config_source(cfg, "ruff")

    assert source.source == "bundled"
    assert source.path.name == "ruff.toml"
    assert source.is_bundled is True


def test_tool_config_source_reports_project_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "pyproject.toml", _BARE)
    (tmp_path / "ruff.toml").write_text("line-length = 99\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    cfg = load_config()
    source = tool_config_source(cfg, "ruff")

    assert source.source == "project: ruff.toml"
    assert source.path == tmp_path / "ruff.toml"
    assert source.is_bundled is False


def test_has_project_config_ignores_other_tool_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "probe"
        version = "0.0.0"

        [tool.black]
        line-length = 99
        """,
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert has_project_config(cfg, "ruff") is False


# ─────────────── tool_config_source matrix (all 4 tools) ────────────────────


_ALL_TOOL_SECTIONS = textwrap.dedent("""
    [project]
    name = "full"
    version = "0.0.0"

    [tool.ruff]
    line-length = 99

    [tool.basedpyright]
    typeCheckingMode = "standard"

    [tool.coverage.run]
    branch = true

    [tool.importlinter]
    root_package = "full"
""")


@pytest.mark.parametrize(
    ("tool", "bundled_filename"),
    [
        ("ruff", "ruff.toml"),
        ("basedpyright", "pyrightconfig.json"),
        ("coverage", "coveragerc"),
        ("import-linter", "importlinter_template.ini"),
    ],
)
def test_tool_config_source_bundled_for_all_tools_in_bare_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
    bundled_filename: str,
) -> None:
    """Every tool reports source='bundled' when the project has no config for it."""
    _write(tmp_path / "pyproject.toml", _BARE)
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    source = tool_config_source(cfg, tool)
    assert source.source == "bundled"
    assert source.path.name == bundled_filename
    assert source.is_bundled is True


@pytest.mark.parametrize(
    ("tool", "section"),
    [
        ("ruff", "ruff"),
        ("basedpyright", "basedpyright"),
        ("coverage", "coverage"),
        ("import-linter", "importlinter"),
    ],
)
def test_tool_config_source_project_for_all_tools_with_full_pyproject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
    section: str,
) -> None:
    """Every tool reports source='project: ...' when its [tool.<section>] is present."""
    _write(tmp_path / "pyproject.toml", _ALL_TOOL_SECTIONS)
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    source = tool_config_source(cfg, tool)
    assert not source.is_bundled
    assert section in source.source


# ─────────────── cross-tool isolation (false-positive guard) ────────────────


@pytest.mark.parametrize(
    ("present_section", "queried_tool"),
    [
        # Having ruff config must not suppress basedpyright, coverage, or import-linter
        ("ruff", "basedpyright"),
        ("ruff", "coverage"),
        ("ruff", "import-linter"),
        # Having basedpyright config must not suppress the other tools
        ("basedpyright", "ruff"),
        ("basedpyright", "coverage"),
        ("basedpyright", "import-linter"),
        # Having coverage config must not suppress the other tools
        ("coverage", "ruff"),
        ("coverage", "basedpyright"),
        ("coverage", "import-linter"),
        # Having importlinter config must not suppress the other tools
        ("importlinter", "ruff"),
        ("importlinter", "basedpyright"),
        ("importlinter", "coverage"),
    ],
)
def test_cross_tool_isolation_single_section_does_not_suppress_others(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    present_section: str,
    queried_tool: str,
) -> None:
    """One tool's [tool.<section>] must never suppress bundled config for a different tool."""
    toml_section = f"\n[tool.{present_section}]\n_placeholder = true\n"
    _write(tmp_path / "pyproject.toml", _BARE + toml_section)
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    source = tool_config_source(cfg, queried_tool)
    assert source.is_bundled, (
        f"[tool.{present_section}] must NOT suppress bundled config for '{queried_tool}', "
        f"but got source={source.source!r}"
    )
