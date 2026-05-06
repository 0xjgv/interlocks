"""Integration tests for `interlocks clean`."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT_DIR_ARTIFACTS = (
    ".ruff_cache",
    "build",
    "dist",
    "htmlcov",
    "mutants",
    ".mutmut-cache",
    ".pytest_cache",
    ".import_linter_cache",
    ".mypy_cache",
    ".interlocks",
    "wheels",
)

ROOT_FILE_ARTIFACTS = (
    ".coverage",
    "mutmut-junit.xml",
    "coverage.xml",
)

ROOT_ARTIFACTS = ROOT_DIR_ARTIFACTS + ROOT_FILE_ARTIFACTS

RECURSIVE_ARTIFACTS = (
    "pkg/__pycache__",
    "pkg/pkg.egg-info",
    "pkg/module.pyc",
    "pkg/module.pyo",
)

SENTINELS = ("src/app.py", "data/raw")


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Minimal project with pre-seeded cache/build artifacts."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "tmpproj"\nversion = "0.0.1"\nrequires-python = ">=3.11"\n',
        encoding="utf-8",
    )
    for d in ROOT_DIR_ARTIFACTS:
        path = tmp_path / d
        path.mkdir()
        (path / "junk").write_text("x", encoding="utf-8")
    for f in ROOT_FILE_ARTIFACTS:
        (tmp_path / f).write_text("x", encoding="utf-8")
    pkg = tmp_path / "pkg"
    nested = pkg / "__pycache__"
    nested.mkdir(parents=True)
    (nested / "foo.pyc").write_text("", encoding="utf-8")
    (pkg / "pkg.egg-info").mkdir()
    (pkg / "module.pyc").write_text("", encoding="utf-8")
    (pkg / "module.pyo").write_text("", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('keep')\n", encoding="utf-8")
    (tmp_path / "data" / "raw").mkdir(parents=True)
    return tmp_path


def test_clean_removes_cache_artifacts(tmp_project: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-P", "-m", "interlocks.cli", "clean"],
        cwd=tmp_project,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "Cleaning Up" in result.stdout
    for name in (*ROOT_ARTIFACTS, *RECURSIVE_ARTIFACTS):
        assert not (tmp_project / name).exists(), f"{name} still present"
    for name in SENTINELS:
        assert (tmp_project / name).exists(), f"{name} missing"


def test_clean_is_idempotent(tmp_project: Path) -> None:
    """Running clean twice should succeed even when nothing is left to remove."""
    cmd = [sys.executable, "-P", "-m", "interlocks.cli", "clean"]
    first = subprocess.run(cmd, cwd=tmp_project, capture_output=True, text=True, check=False)
    second = subprocess.run(cmd, cwd=tmp_project, capture_output=True, text=True, check=False)

    assert first.returncode == 0
    assert second.returncode == 0
    assert "[clean]" in second.stdout


def test_clean_in_process_removes_artifacts(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from interlocks.stages import clean as clean_mod

    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(clean_mod, "run", lambda *a, **k: None)
    clean_mod.cmd_clean()

    for name in (*ROOT_ARTIFACTS, *RECURSIVE_ARTIFACTS):
        assert not (tmp_project / name).exists(), f"{name} still present"
    for name in SENTINELS:
        assert (tmp_project / name).exists(), f"{name} missing"
