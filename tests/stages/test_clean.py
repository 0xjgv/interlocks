"""Integration tests for `harness clean`."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Minimal project with pre-seeded cache/build artifacts."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "tmpproj"\nversion = "0.0.1"\nrequires-python = ">=3.13"\n',
        encoding="utf-8",
    )
    for d in (".ruff_cache", "__pycache__", "htmlcov", "build", "dist", ".mutmut-cache"):
        (tmp_path / d).mkdir()
    (tmp_path / ".ruff_cache" / "junk").write_text("x", encoding="utf-8")
    (tmp_path / ".coverage").write_text("", encoding="utf-8")
    (tmp_path / "mutmut-junit.xml").write_text("<x/>", encoding="utf-8")
    nested = tmp_path / "pkg" / "__pycache__"
    nested.mkdir(parents=True)
    (nested / "foo.pyc").write_text("", encoding="utf-8")
    return tmp_path


def test_clean_removes_cache_artifacts(tmp_project: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-P", "-m", "harness.cli", "clean"],
        cwd=tmp_project,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "Cleaning Up" in result.stdout
    for name in (
        ".ruff_cache",
        "__pycache__",
        "htmlcov",
        "build",
        "dist",
        ".mutmut-cache",
        ".coverage",
        "mutmut-junit.xml",
    ):
        assert not (tmp_project / name).exists(), f"{name} still present"
    assert not (tmp_project / "pkg" / "__pycache__").exists()


def test_clean_is_idempotent(tmp_project: Path) -> None:
    """Running clean twice should succeed even when nothing is left to remove."""
    cmd = [sys.executable, "-P", "-m", "harness.cli", "clean"]
    first = subprocess.run(cmd, cwd=tmp_project, capture_output=True, text=True, check=False)
    second = subprocess.run(cmd, cwd=tmp_project, capture_output=True, text=True, check=False)

    assert first.returncode == 0
    assert second.returncode == 0
    assert "[clean]" in second.stdout


def test_clean_in_process_removes_artifacts(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from harness.stages import clean as clean_mod

    monkeypatch.chdir(tmp_project)
    # Stub the ruff subprocess — we only care about the filesystem cleanup path.
    monkeypatch.setattr(clean_mod, "run", lambda *a, **k: None)
    clean_mod.cmd_clean()

    for name in (
        ".ruff_cache",
        "__pycache__",
        "htmlcov",
        "build",
        "dist",
        ".mutmut-cache",
        ".coverage",
        "mutmut-junit.xml",
    ):
        assert not (tmp_project / name).exists(), f"{name} still present"
    assert not (tmp_project / "pkg" / "__pycache__").exists()
