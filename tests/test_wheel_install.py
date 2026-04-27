"""Wheel-install smoke tests for packaged CLI entry points and hooks."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

REPO_ROOT = Path(__file__).resolve().parent.parent


def _project_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _run(cmd: list[str | Path], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(part) for part in cmd],
        check=True,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX venv layout assumed")
def test_wheel_installs_cli_entrypoints_and_hooks(tmp_path: Path) -> None:
    if shutil.which("uv") is None:
        pytest.skip("uv required")

    dist_dir = tmp_path / "dist"
    _run(["uv", "build", "--out-dir", dist_dir, REPO_ROOT], cwd=tmp_path)

    wheels = list(dist_dir.glob("*.whl"))
    assert wheels, f"no wheel produced in {dist_dir}"
    wheel = wheels[0]

    _run(["uv", "venv", "venv"], cwd=tmp_path)

    venv_python = tmp_path / "venv" / "bin" / "python"
    _run(["uv", "pip", "install", wheel, "--python", venv_python], cwd=tmp_path)

    interlocks_bin = tmp_path / "venv" / "bin" / "interlocks"
    il_bin = tmp_path / "venv" / "bin" / "il"
    for bin_path in (interlocks_bin, il_bin):
        assert bin_path.exists(), f"entry point missing at {bin_path}"
        assert bin_path.stat().st_mode & 0o111, f"entry point not executable at {bin_path}"

    result = _run([interlocks_bin, "help"], cwd=tmp_path)
    for expected in ("check", "pre-commit", "ci", "nightly"):
        assert expected in result.stdout, (
            f"`interlocks help` output missing {expected!r}:\n{result.stdout}"
        )

    version = _project_version()
    assert _run([il_bin, "version"], cwd=tmp_path).stdout.strip() == version
    assert (
        _run([venv_python, "-m", "interlocks.cli", "version"], cwd=tmp_path).stdout.strip()
        == version
    )
    assert (
        _run(
            [venv_python, "-c", "import interlocks; print(interlocks.__version__)"], cwd=tmp_path
        ).stdout.strip()
        == version
    )

    setup_project = tmp_path / "setup-project"
    setup_project.mkdir()
    (setup_project / "pyproject.toml").write_text(
        '[project]\nname = "setup-smoke"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    (setup_project / ".git").mkdir()

    _run([il_bin, "setup-hooks"], cwd=setup_project)

    pre_commit = (setup_project / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8")
    settings = (setup_project / ".claude" / "settings.json").read_text(encoding="utf-8")
    assert "-m interlocks.cli pre-commit" in pre_commit
    assert "-m interlocks.cli post-edit" in settings
    assert "-m interlock.cli" not in pre_commit
    assert "-m interlock.cli" not in settings
