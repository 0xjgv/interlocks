"""Tests for the dormant `mutation_ci_mode` + `mutation_since_ref` config fields."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from interlocks.config import load_config


def _setup_pyproject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> Path:
    """Create ``tmp_path/tests`` + ``pyproject.toml`` with ``body`` and chdir."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(textwrap.dedent(body), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_defaults_when_unset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "dflt"
        version = "0.0.0"
        """,
    )
    cfg = load_config()
    assert cfg.mutation_ci_mode == "off"
    assert cfg.mutation_since_ref == "origin/main"


def test_project_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "proj"
        version = "0.0.0"

        [tool.interlocks]
        mutation_ci_mode = "incremental"
        mutation_since_ref = "origin/develop"
        """,
    )
    cfg = load_config()
    assert cfg.mutation_ci_mode == "incremental"
    assert cfg.mutation_since_ref == "origin/develop"


def test_invalid_mode_falls_back_to_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "badmode"
        version = "0.0.0"

        [tool.interlocks]
        mutation_ci_mode = "sometimes"
        """,
    )
    cfg = load_config()
    assert cfg.mutation_ci_mode == "off"


def test_invalid_since_ref_type_falls_back_to_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "badref"
        version = "0.0.0"

        [tool.interlocks]
        mutation_since_ref = 42
        """,
    )
    cfg = load_config()
    assert cfg.mutation_since_ref == "origin/main"


# ─────────────── changed_ref (for `interlocks check --changed`) ────────────────


def test_changed_ref_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "ch-default"
        version = "0.0.0"
        """,
    )
    cfg = load_config()
    assert cfg.changed_ref == "origin/main"
    assert cfg.value_sources["changed_ref"] == "bundled-default"


def test_changed_ref_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "ch-override"
        version = "0.0.0"

        [tool.interlocks]
        changed_ref = "HEAD"
        """,
    )
    cfg = load_config()
    assert cfg.changed_ref == "HEAD"
    assert cfg.value_sources["changed_ref"] == "project-configured"


def test_invalid_changed_ref_type_falls_back_to_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "ch-bad"
        version = "0.0.0"

        [tool.interlocks]
        changed_ref = 42
        """,
    )
    cfg = load_config()
    assert cfg.changed_ref == "origin/main"
