"""Escrow writer: creates ``.lintfix/escrow/<rule>.patch`` with correct content."""

from __future__ import annotations

from pathlib import Path

from interlocks.lintfix.escrow import escrow_dir, write_failed_patch, write_patch


def test_escrow_dir_is_under_project_root(tmp_path: Path) -> None:
    assert escrow_dir(tmp_path) == tmp_path / ".lintfix" / "escrow"


def test_write_patch_creates_dirs_and_file(tmp_path: Path) -> None:
    target = write_patch(tmp_path, "I001", "--- a\n+++ b\n")
    assert target == tmp_path / ".lintfix" / "escrow" / "I001.patch"
    assert target.read_text() == "--- a\n+++ b\n"


def test_write_patch_overwrites(tmp_path: Path) -> None:
    write_patch(tmp_path, "F401", "first")
    target = write_patch(tmp_path, "F401", "second")
    assert target.read_text() == "second"


def test_write_failed_patch(tmp_path: Path) -> None:
    target = write_failed_patch(tmp_path, "boom")
    assert target == tmp_path / ".lintfix" / "failed.patch"
    assert target.read_text() == "boom"
