"""EOF newline helper: idempotent + safe on empty/missing/clean files."""

from __future__ import annotations

from pathlib import Path

from interlocks.lintfix.eof_newline import ensure_trailing_newline


def test_appends_when_missing(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_bytes(b"x = 1")
    assert ensure_trailing_newline(f) is True
    assert f.read_bytes() == b"x = 1\n"


def test_idempotent_on_clean_file(tmp_path: Path) -> None:
    f = tmp_path / "b.py"
    f.write_bytes(b"x = 1\n")
    assert ensure_trailing_newline(f) is False
    assert ensure_trailing_newline(f) is False
    assert f.read_bytes() == b"x = 1\n"


def test_skips_empty_file(tmp_path: Path) -> None:
    f = tmp_path / "empty.py"
    f.write_bytes(b"")
    assert ensure_trailing_newline(f) is False
    assert f.read_bytes() == b""


def test_returns_false_for_missing_path(tmp_path: Path) -> None:
    assert ensure_trailing_newline(tmp_path / "nope.py") is False
