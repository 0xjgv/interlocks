"""Idempotent EOF newline helper.

Appends a single ``\\n`` only when the file is non-empty and missing one —
no churn on already-clean files.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def ensure_trailing_newline(path: Path) -> bool:
    """Append ``\\n`` to ``path`` iff non-empty and missing one. Returns ``True`` when written."""
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if not data or data.endswith(b"\n"):
        return False
    with path.open("ab") as f:
        f.write(b"\n")
    return True
