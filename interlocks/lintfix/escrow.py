"""Patch escrow — write unapplied candidate patches to ``.lintfix/``."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def lintfix_dir(project_root: Path) -> Path:
    """Return ``.lintfix/`` rooted at ``project_root`` (not created)."""
    return project_root / ".lintfix"


def escrow_dir(project_root: Path) -> Path:
    """Return ``.lintfix/escrow/`` rooted at ``project_root`` (not created)."""
    return lintfix_dir(project_root) / "escrow"


def write_patch(project_root: Path, rule: str, patch_text: str) -> Path:
    """Write ``patch_text`` to ``.lintfix/escrow/<rule>.patch``."""
    return _write(escrow_dir(project_root) / f"{rule}.patch", patch_text)


def write_failed_patch(project_root: Path, patch_text: str) -> Path:
    """Write a failed-verification patch to ``.lintfix/failed.patch``."""
    return _write(lintfix_dir(project_root) / "failed.patch", patch_text)


def _write(target: Path, text: str) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target
