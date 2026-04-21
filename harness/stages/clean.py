"""Remove cache and build artifacts."""

from __future__ import annotations

import shutil
from pathlib import Path

from harness.runner import run


def cmd_clean() -> None:
    """Remove cache and build artifacts."""
    print("\n=== Cleaning Up ===\n")
    for name in [".ruff_cache", "build", "dist", "htmlcov"]:
        p = Path(name)
        if p.is_dir():
            shutil.rmtree(p)
    for name in [".coverage"]:
        p = Path(name)
        if p.is_file():
            p.unlink()
    for p in Path().rglob("__pycache__"):
        shutil.rmtree(p)
    run("Ruff clean", ["uv", "run", "ruff", "clean"])
