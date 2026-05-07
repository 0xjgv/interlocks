"""Remove cache, build, coverage, and generated artifacts."""

from __future__ import annotations

import os
import shutil
import time
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from interlocks import ui
from interlocks.config import load_config
from interlocks.metrics import PY_SKIP_DIRS
from interlocks.runner import Task, run, tool

if TYPE_CHECKING:
    from collections.abc import Iterator

ROOT_ARTIFACTS = (
    ".ruff_cache",
    "build",
    "dist",
    "htmlcov",
    ".coverage",
    "mutants",
    ".mutmut-cache",
    "mutmut-junit.xml",
    ".pytest_cache",
    ".import_linter_cache",
    ".mypy_cache",
    ".interlocks",
    "wheels",
    "coverage.xml",
)

RECURSIVE_FILE_SUFFIXES = (".pyc", ".pyo")
RECURSIVE_SKIP_DIRS = PY_SKIP_DIRS | frozenset({".git"})


def cmd_clean() -> None:
    """Remove cache, build, coverage, and generated artifacts."""
    start = time.monotonic()
    ui.banner(load_config())
    ui.section("Cleaning Up")
    try:
        for name in ROOT_ARTIFACTS:
            _remove_path(Path(name))
        for path in _iter_recursive_artifacts(Path()):
            _remove_path(path)
        run(Task("Ruff clean", tool("ruff", "clean"), label="clean", display="ruff clean"))
    finally:
        ui.stage_footer(time.monotonic() - start)


def _iter_recursive_artifacts(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        artifact_dirs = [
            name for name in dirnames if name == "__pycache__" or name.endswith(".egg-info")
        ]
        dirnames[:] = [
            name
            for name in dirnames
            if name not in RECURSIVE_SKIP_DIRS and name not in artifact_dirs
        ]
        base = Path(dirpath)
        for dirname in artifact_dirs:
            yield base / dirname
        for filename in filenames:
            if filename.endswith(RECURSIVE_FILE_SUFFIXES):
                yield base / filename


def _remove_path(path: Path) -> None:
    with suppress(FileNotFoundError):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
