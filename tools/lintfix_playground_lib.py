"""Shared fixtures for local lint-fix playground and e2e scripts."""

from __future__ import annotations

import shutil
import subprocess  # noqa: S404
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLAYGROUNDS_ROOT = REPO_ROOT / ".factory" / "playgrounds"
GIT = shutil.which("git") or "git"

PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "lintfix-optimizer-playground"
    version = "0.0.0"
    requires-python = ">=3.11"

    [dependency-groups]
    dev = ["pytest>=9"]

    [tool.ruff]
    target-version = "py311"
    line-length = 99

    [tool.ruff.lint]
    select = ["F", "I", "W", "UP", "SIM"]

    [tool.coverage.run]
    source = ["src/playground"]
    branch = true

    [tool.coverage.report]
    fail_under = 0

    [tool.interlocks]
    src_dir = "src/playground"
    test_dir = "tests"
    coverage_min = 0
    crap_max = 1000.0
    enforce_crap = false
    skip = ["audit", "deps"]
    """
)

CLEAN_FILES: dict[str, str] = {
    "src/playground/__init__.py": '"""Playground package."""\n',
    "src/playground/imports.py": textwrap.dedent(
        """\
        import os
        import sys


        def environment() -> str:
            return f"{sys.version_info.major}:{os.name}"
        """
    ),
    "src/playground/newline.py": "VALUE = 1\n",
    "src/playground/types.py": textwrap.dedent(
        """\
        def coerce(value: int | None) -> int:
            return value or 0
        """
    ),
    "src/playground/simplify.py": textwrap.dedent(
        """\
        def is_enabled(value: bool) -> bool:
            return value
        """
    ),
    "tests/test_smoke.py": textwrap.dedent(
        """\
        from playground.imports import environment


        def test_environment() -> None:
            assert environment()
        """
    ),
}

DIRTY_FILES: dict[str, str] = {
    "src/playground/imports.py": textwrap.dedent(
        """\
        import sys
        import os
        import json


        def environment() -> str:
            return f"{sys.version_info.major}:{os.name}"
        """
    ),
    "src/playground/newline.py": "VALUE = 1",
    "src/playground/types.py": textwrap.dedent(
        """\
        from typing import Optional


        def coerce(value: Optional[int]) -> int:
            return value or 0
        """
    ),
    "src/playground/simplify.py": textwrap.dedent(
        """\
        def is_enabled(value: bool) -> bool:
            if value == True:
                return True
            return False
        """
    ),
}

REPLAY_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "lintfix-replay-playground"
    version = "0.0.0"
    requires-python = ">=3.11"

    [tool.ruff]
    target-version = "py311"
    line-length = 99

    [tool.ruff.lint]
    select = ["I"]
    """
)

REPLAY_CLEAN_IMPORTS = "import os\nimport sys\n\nprint(os.name, sys.version)\n"
REPLAY_REORDERED_IMPORTS = "import sys\nimport os\n\nprint(os.name, sys.version)\n"


def create_optimizer_repo(target: Path, *, playgrounds_root: Path = PLAYGROUNDS_ROOT) -> Path:
    """Recreate ``target`` as a dirty nested repo for lint-fix commands."""
    target = _prepare_target(target, playgrounds_root=playgrounds_root)
    write_text(target / "pyproject.toml", PYPROJECT)
    write_files(target, CLEAN_FILES)
    init_git_repo(target)
    git(target, "add", "-A")
    git(target, "commit", "-q", "-m", "baseline")
    write_files(target, DIRTY_FILES)
    return target


def create_replay_repo(target: Path, *, playgrounds_root: Path = PLAYGROUNDS_ROOT) -> Path:
    """Recreate ``target`` as a nested repo with a small replayable history."""
    target = _prepare_target(target, playgrounds_root=playgrounds_root)
    write_text(target / "pyproject.toml", REPLAY_PYPROJECT)
    write_text(target / "a.py", REPLAY_CLEAN_IMPORTS)
    init_git_repo(target)
    git(target, "add", "-A")
    git(target, "commit", "-q", "-m", "baseline")

    write_text(target / "a.py", REPLAY_REORDERED_IMPORTS)
    git(target, "add", "-A")
    git(target, "commit", "-q", "-m", "reorder a")

    write_text(target / "b.py", REPLAY_REORDERED_IMPORTS)
    git(target, "add", "-A")
    git(target, "commit", "-q", "-m", "add b with reorder")
    return target


def init_git_repo(target: Path) -> None:
    git(target, "init", "-q", "-b", "main")
    git(target, "config", "user.email", "test@example.com")
    git(target, "config", "user.name", "Test")
    git(target, "config", "commit.gpgsign", "false")
    git(target, "config", "core.hooksPath", "/dev/null")


def write_files(root: Path, files: dict[str, str]) -> None:
    for relpath, content in files.items():
        write_text(root / relpath, content)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [GIT, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


def _prepare_target(target: Path, *, playgrounds_root: Path) -> Path:
    target = target.resolve()
    root = playgrounds_root.resolve()
    if root not in target.parents:
        msg = f"refusing to recreate target outside {root}: {target}"
        raise ValueError(msg)
    if target == root:
        msg = f"refusing to recreate playground root itself: {target}"
        raise ValueError(msg)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    return target
