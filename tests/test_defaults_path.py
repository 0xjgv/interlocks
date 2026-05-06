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
    _write(tmp_path / "pyproject.toml", "[project]\nname='probe'\nversion='0.0.0'\n")
    (tmp_path / "ruff.toml").write_text("line-length = 99\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert has_project_config(cfg, "ruff", sidecars=("ruff.toml", ".ruff.toml")) is True


def test_has_project_config_returns_false_when_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "pyproject.toml", "[project]\nname='probe'\nversion='0.0.0'\n")
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert has_project_config(cfg, "ruff", sidecars=("ruff.toml",)) is False


def test_tool_config_source_reports_bundled_when_project_config_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "pyproject.toml", "[project]\nname='probe'\nversion='0.0.0'\n")
    monkeypatch.chdir(tmp_path)

    cfg = load_config()
    source = tool_config_source(cfg, "ruff")

    assert source.source == "bundled"
    assert source.path.name == "ruff.toml"
    assert source.is_bundled is True


def test_tool_config_source_reports_project_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "pyproject.toml", "[project]\nname='probe'\nversion='0.0.0'\n")
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
