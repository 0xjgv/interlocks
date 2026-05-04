"""Tests for the dormant `mutation_ci_mode` + `mutation_since_ref` config fields."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from interlocks.config import load_config


def _write(path: Path, text: str) -> None:
    path.write_text(textwrap.dedent(text), encoding="utf-8")


def test_defaults_when_unset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "tests").mkdir()
    _write(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "dflt"
        version = "0.0.0"
        """,
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.mutation_ci_mode == "off"
    assert cfg.mutation_since_ref == "origin/main"


def test_project_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "tests").mkdir()
    _write(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "proj"
        version = "0.0.0"

        [tool.interlocks]
        mutation_ci_mode = "incremental"
        mutation_since_ref = "origin/develop"
        """,
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.mutation_ci_mode == "incremental"
    assert cfg.mutation_since_ref == "origin/develop"


def test_invalid_mode_falls_back_to_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "tests").mkdir()
    _write(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "badmode"
        version = "0.0.0"

        [tool.interlocks]
        mutation_ci_mode = "sometimes"
        """,
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.mutation_ci_mode == "off"


def test_invalid_since_ref_type_falls_back_to_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "tests").mkdir()
    _write(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "badref"
        version = "0.0.0"

        [tool.interlocks]
        mutation_since_ref = 42
        """,
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.mutation_since_ref == "origin/main"


# ─────────────── changed_ref (for `interlocks check --changed`) ────────────────


def test_changed_ref_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "tests").mkdir()
    _write(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "ch-default"
        version = "0.0.0"
        """,
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.changed_ref == "origin/main"
    assert cfg.value_sources["changed_ref"] == "bundled-default"


def test_changed_ref_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "tests").mkdir()
    _write(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "ch-override"
        version = "0.0.0"

        [tool.interlocks]
        changed_ref = "HEAD"
        """,
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.changed_ref == "HEAD"
    assert cfg.value_sources["changed_ref"] == "project-configured"


def test_invalid_changed_ref_type_falls_back_to_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "tests").mkdir()
    _write(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "ch-bad"
        version = "0.0.0"

        [tool.interlocks]
        changed_ref = 42
        """,
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.changed_ref == "origin/main"
