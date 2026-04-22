"""Tests for the dormant `mutation_ci_mode` + `mutation_since_ref` config fields."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from harness.config import load_config


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

        [tool.harness]
        mutation_ci_mode = "incremental"
        mutation_since_ref = "origin/develop"
        """,
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.mutation_ci_mode == "incremental"
    assert cfg.mutation_since_ref == "origin/develop"


def test_user_global_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "tests").mkdir()
    _write(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "ug"
        version = "0.0.0"
        """,
    )
    home = tmp_path / "fake_home"
    (home / ".config" / "harness").mkdir(parents=True)
    (home / ".config" / "harness" / "config.toml").write_text(
        'mutation_ci_mode = "full"\nmutation_since_ref = "main"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.mutation_ci_mode == "full"
    assert cfg.mutation_since_ref == "main"


def test_project_wins_over_user_global(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "tests").mkdir()
    _write(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "pwins"
        version = "0.0.0"

        [tool.harness]
        mutation_ci_mode = "incremental"
        """,
    )
    home = tmp_path / "fake_home"
    (home / ".config" / "harness").mkdir(parents=True)
    (home / ".config" / "harness" / "config.toml").write_text(
        'mutation_ci_mode = "full"\nmutation_since_ref = "origin/dev"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.mutation_ci_mode == "incremental"  # project wins
    assert cfg.mutation_since_ref == "origin/dev"  # user-global fills in


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

        [tool.harness]
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

        [tool.harness]
        mutation_since_ref = 42
        """,
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.mutation_since_ref == "origin/main"
