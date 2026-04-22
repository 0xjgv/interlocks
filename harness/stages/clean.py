"""Remove cache and build artifacts."""

from __future__ import annotations

import shutil
from pathlib import Path

from harness.runner import run, tool


def cmd_clean() -> None:
    """Remove cache and build artifacts."""
    print("\n=== Cleaning Up ===\n")
    for name in [
        ".ruff_cache",
        "build",
        "dist",
        "htmlcov",
        ".coverage",
        "mutants",
        ".mutmut-cache",
        "mutmut-junit.xml",
    ]:
        p = Path(name)
        if p.is_dir():
            shutil.rmtree(p)
        elif p.is_file():
            p.unlink()
    for p in Path().rglob("__pycache__"):
        shutil.rmtree(p)
    run("Ruff clean", tool("ruff", "clean"))
