"""Wheel-install smoke test.

Builds the pyharness wheel, installs it into a clean venv, and runs
`harness help`. Guards the `pipx install pyharness` promise from the README
against packaging regressions (e.g. missing `harness/defaults/*` data files).

Marked `slow` because building a wheel and creating a fresh venv takes several
seconds; the `slow` marker is registered in pyproject.toml. Opt in with
`pytest -m slow`.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow


REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX venv layout assumed")
def test_wheel_installs_and_harness_help_runs(tmp_path: Path) -> None:
    if shutil.which("uv") is None:
        pytest.skip("uv required")

    dist_dir = tmp_path / "dist"
    build_cmd = ["uv", "build", "--out-dir", str(dist_dir), str(REPO_ROOT)]
    subprocess.run(build_cmd, check=True, cwd=tmp_path)

    wheels = list(dist_dir.glob("*.whl"))
    assert wheels, f"no wheel produced in {dist_dir}"
    wheel = wheels[0]

    venv_cmd = ["uv", "venv", "venv"]
    subprocess.run(venv_cmd, check=True, cwd=tmp_path)

    venv_python = tmp_path / "venv" / "bin" / "python"
    install_cmd = ["uv", "pip", "install", str(wheel), "--python", str(venv_python)]
    subprocess.run(install_cmd, check=True, cwd=tmp_path)

    harness_bin = tmp_path / "venv" / "bin" / "harness"
    assert harness_bin.exists(), f"harness entry point missing at {harness_bin}"
    assert harness_bin.stat().st_mode & 0o111, "harness entry point not executable"

    result = subprocess.run(
        [str(harness_bin), "help"],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    for expected in ("check", "pre-commit", "ci", "nightly"):
        assert expected in result.stdout, (
            f"`harness help` output missing {expected!r}:\n{result.stdout}"
        )
