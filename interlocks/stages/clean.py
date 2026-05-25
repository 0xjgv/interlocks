"""Remove cache, build, coverage, and generated artifacts."""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from interlocks import ui
from interlocks.config import load_config
from interlocks.metrics import PY_SKIP_DIRS
from interlocks.runner import Task, reset_results, results_snapshot, run, stage_json, uvx_tool

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
_REMOVED_SAMPLE_LIMIT = 50


def cmd_clean() -> None:
    """Remove cache, build, coverage, and generated artifacts."""
    start = time.monotonic()
    cfg = load_config()
    reset_results()
    ui.banner(cfg)
    ui.section("Cleaning Up")
    removed: list[str] = []
    try:
        removed = _remove_artifacts(Path())
        run(
            Task(
                "Ruff clean",
                uvx_tool("ruff", "clean", version=cfg.tool_version("ruff")),
                label="clean",
                display="ruff clean",
            ),
            no_exit=ui.is_json(),
        )
    finally:
        elapsed = time.monotonic() - start
        ui.stage_footer(elapsed)
    if ui.is_json():
        payload = _clean_payload(removed, elapsed)
        ui.print_json(payload)
        if not payload["passed"]:
            sys.exit(1)


def _remove_artifacts(root: Path) -> list[str]:
    removed: list[str] = []
    for name in ROOT_ARTIFACTS:
        path = root / name
        if _remove_path(path):
            removed.append(_artifact_label(root, path))
    for path in _iter_recursive_artifacts(root):
        if _remove_path(path):
            removed.append(_artifact_label(root, path))
    return removed


def _is_artifact_dir(name: str) -> bool:
    return name == "__pycache__" or name.endswith(".egg-info")


def _iter_recursive_artifacts(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        artifact_dirs = [name for name in dirnames if _is_artifact_dir(name)]
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


def _remove_path(path: Path) -> bool:
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    except FileNotFoundError:
        return False
    return True


def _artifact_label(root: Path, path: Path) -> str:
    try:
        label = path.relative_to(root).as_posix()
    except ValueError:
        label = path.as_posix()
    return label.removeprefix("./")


def _clean_payload(removed: list[str], elapsed: float) -> dict[str, object]:
    passed = all(result.status == "ok" for result in results_snapshot())
    payload = stage_json("clean", passed=passed, elapsed=elapsed)
    payload["status"] = "cleaned" if passed else "failed"
    payload.update(_removed_payload_fields(removed))
    return payload


def _removed_payload_fields(removed: list[str]) -> dict[str, object]:
    fields: dict[str, object] = {
        "removed_count": len(removed),
        "removed": removed[:_REMOVED_SAMPLE_LIMIT],
    }
    omitted = len(removed) - _REMOVED_SAMPLE_LIMIT
    if omitted > 0:
        fields["omitted_removed"] = omitted
    return fields
