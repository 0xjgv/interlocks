"""Tests for detect_features_dir + detect_acceptance_runner."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from harness.config import HarnessConfig, clear_cache, load_config
from harness.detect import detect_acceptance_runner, detect_features_dir

_MINIMAL_PYPROJECT = '[project]\nname="probe"\nversion="0.0.0"\n'


def _cfg(
    project_root: Path,
    *,
    pyproject_body: str = _MINIMAL_PYPROJECT,
    **overrides: object,
) -> HarnessConfig:
    """Build a HarnessConfig rooted at ``project_root`` with optional field overrides."""
    (project_root / "pyproject.toml").write_text(pyproject_body, encoding="utf-8")
    clear_cache()
    return replace(load_config(project_root), project_root=project_root, **overrides)


def test_detect_features_dir_prefers_tests_features(tmp_path: Path) -> None:
    (tmp_path / "tests" / "features").mkdir(parents=True)
    (tmp_path / "features").mkdir()
    assert (
        detect_features_dir(tmp_path, tmp_path / "tests")
        == (tmp_path / "tests" / "features").resolve()
    )


def test_detect_features_dir_falls_back_to_top_level(tmp_path: Path) -> None:
    (tmp_path / "features").mkdir()
    assert detect_features_dir(tmp_path, tmp_path / "tests") == (tmp_path / "features").resolve()


def test_detect_features_dir_inside_test_dir(tmp_path: Path) -> None:
    (tmp_path / "custom_tests" / "features").mkdir(parents=True)
    assert (
        detect_features_dir(tmp_path, tmp_path / "custom_tests")
        == (tmp_path / "custom_tests" / "features").resolve()
    )


def test_detect_features_dir_none_when_absent(tmp_path: Path) -> None:
    assert detect_features_dir(tmp_path, tmp_path / "tests") is None


def test_detect_acceptance_runner_none_without_features(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, features_dir=None)
    assert detect_acceptance_runner(cfg) is None


def test_detect_acceptance_runner_defaults_to_pytest_bdd(tmp_path: Path) -> None:
    features = tmp_path / "tests" / "features"
    features.mkdir(parents=True)
    cfg = _cfg(tmp_path, features_dir=features)
    assert detect_acceptance_runner(cfg) == "pytest-bdd"


def test_detect_acceptance_runner_behave_from_layout(tmp_path: Path) -> None:
    features = tmp_path / "features"
    (features / "steps").mkdir(parents=True)
    (features / "environment.py").write_text("", encoding="utf-8")
    cfg = _cfg(tmp_path, features_dir=features)
    assert detect_acceptance_runner(cfg) == "behave"


def test_detect_acceptance_runner_behave_from_deps(tmp_path: Path) -> None:
    features = tmp_path / "features"
    features.mkdir()
    cfg = _cfg(
        tmp_path,
        pyproject_body=_MINIMAL_PYPROJECT + '[dependency-groups]\ndev = ["behave>=1.2"]\n',
        features_dir=features,
    )
    assert detect_acceptance_runner(cfg) == "behave"


def test_detect_acceptance_runner_pytest_bdd_beats_behave_in_deps(tmp_path: Path) -> None:
    """When both deps are declared, prefer pytest-bdd (the default runner)."""
    features = tmp_path / "features"
    features.mkdir()
    cfg = _cfg(
        tmp_path,
        pyproject_body=_MINIMAL_PYPROJECT
        + '[dependency-groups]\ndev = ["behave>=1.2", "pytest-bdd>=6.1"]\n',
        features_dir=features,
    )
    assert detect_acceptance_runner(cfg) == "pytest-bdd"


def test_detect_acceptance_runner_override_off(tmp_path: Path) -> None:
    features = tmp_path / "features"
    features.mkdir()
    cfg = _cfg(tmp_path, features_dir=features, acceptance_runner="off")
    assert detect_acceptance_runner(cfg) is None


def test_detect_acceptance_runner_override_forces_behave(tmp_path: Path) -> None:
    features = tmp_path / "tests" / "features"
    features.mkdir(parents=True)  # no behave layout
    cfg = _cfg(tmp_path, features_dir=features, acceptance_runner="behave")
    assert detect_acceptance_runner(cfg) == "behave"
