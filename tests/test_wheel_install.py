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

    def run(cmd: list[str | Path], *, cwd: Path = tmp_path) -> subprocess.CompletedProcess[str]:
        return _run(cmd, cwd=cwd)

    dist_dir = tmp_path / "dist"
    run(["uv", "build", "--out-dir", dist_dir, REPO_ROOT])

    wheels = list(dist_dir.glob("*.whl"))
    assert wheels, f"no wheel produced in {dist_dir}"
    wheel = wheels[0]

    venv = tmp_path / "venv"
    run(["uv", "venv", venv])

    venv_python = venv / "bin" / "python"
    run(["uv", "pip", "install", wheel, "--python", venv_python])

    all_aliases = ("interlocks", "ilocks", "ilock", "ils", "il")
    for alias in all_aliases:
        bin_path = venv / "bin" / alias
        assert bin_path.exists(), f"entry point missing: {alias} at {bin_path}"
        assert bin_path.stat().st_mode & 0o111, f"entry point not executable: {alias}"

    interlocks_bin = venv / "bin" / "interlocks"
    il_bin = venv / "bin" / "il"

    help_out = run([interlocks_bin, "help", "--advanced"]).stdout
    for expected in ("check", "ci", "pre-commit", "nightly"):
        tag = f"[{expected}]"
        assert tag in help_out, f"help --advanced missing {tag!r}"

    version = _project_version()
    version_cmds: list[list[str | Path]] = [
        [il_bin, "version"],
        [venv_python, "-m", "interlocks.cli", "version"],
        [venv_python, "-c", "import interlocks; print(interlocks.__version__)"],
    ]
    for cmd in version_cmds:
        assert run(cmd).stdout.strip() == version, cmd

    # Verify bundled default configs ship inside the wheel and are resolvable
    # via interlocks.defaults_path (importlib.resources) — the runtime mechanism
    # used by every tool dispatch that lacks a project-native config.
    bundled_probe = "\n".join([
        "from interlocks.defaults_path import path",
        *[
            f"assert path({n!r}).is_file(), f'bundled default missing: {n}'"
            for n in ("ruff.toml", "coveragerc", "pyrightconfig.json", "importlinter_template.ini")
        ],
    ])
    run([venv_python, "-c", bundled_probe])

    setup_project = tmp_path / "setup-project"
    setup_project.mkdir()
    (setup_project / "pyproject.toml").write_text(
        '[project]\nname = "setup-smoke"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    (setup_project / ".git").mkdir()

    run([il_bin, "setup-hooks"], cwd=setup_project)

    pre_commit = (setup_project / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8")
    settings = (setup_project / ".claude" / "settings.json").read_text(encoding="utf-8")
    assert "-m interlocks.cli pre-commit" in pre_commit
    assert "-m interlocks.cli post-edit" in settings
    assert "-m interlock.cli" not in pre_commit
    assert "-m interlock.cli" not in settings
