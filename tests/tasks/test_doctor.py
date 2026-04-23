"""Tests for `harness doctor` preflight diagnostic."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import harness

# When running under an outer interpreter whose site-packages .pth shadows
# this checkout (e.g. a parent-repo pre-commit hook), point the subprocess's
# PYTHONPATH at the in-tree harness so `python -m harness.cli` sees the
# code under test — not the shadowed install.
_HARNESS_PARENT = str(Path(harness.__file__).resolve().parent.parent)


def _run_doctor(cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{_HARNESS_PARENT}{os.pathsep}{existing}" if existing else _HARNESS_PARENT
    return subprocess.run(
        [sys.executable, "-P", "-m", "harness.cli", "doctor"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_doctor_tmpdir_flags_missing_pyproject(tmp_path: Path) -> None:
    result = _run_doctor(tmp_path)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "pyproject.toml" in result.stdout
    assert "(missing)" in result.stdout
    # Section headers show up so the report is grouped, not a blob.
    assert "Project:" in result.stdout
    assert "Tools:" in result.stdout
    assert "Venv:" in result.stdout
    assert "Summary:" in result.stdout


def test_doctor_in_process_reports_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """In-process call gives coverage of the happy path under a tmp project."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "probe"\nversion = "0.0.0"\nrequires-python = ">=3.13"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    from harness.config import clear_cache
    from harness.tasks.doctor import cmd_doctor, task_doctor

    clear_cache()
    try:
        cmd_doctor()
    finally:
        clear_cache()

    captured = capsys.readouterr()
    assert "Project:" in captured.out
    assert "src_dir" in captured.out
    assert "test_runner" in captured.out
    assert "Summary:" in captured.out
    # task_doctor is CLI-only — it never composes into a stage pipeline.
    assert task_doctor() is None
