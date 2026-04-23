"""Safe-swap context manager for ``[tool.mutmut].paths_to_mutate``.

Atomically rewrites the ``paths_to_mutate`` key for the duration of the ``with``
block, restoring the original bytes on normal exit, exception, or SIGTERM/SIGINT.
Stdlib-only: ``tomllib`` is read-only, so writes go through a targeted regex
replace on the single-line array form. Multi-line arrays raise ``ValueError``.
"""

from __future__ import annotations

import atexit
import json
import os
import re
import signal
import tempfile
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import FrameType

_MUTMUT_HEADER = re.compile(r"^\[tool\.mutmut\]\s*$", re.MULTILINE)
_NEXT_HEADER = re.compile(r"^\[", re.MULTILINE)
_PATHS_LINE = re.compile(r"^(?P<indent>[ \t]*)paths_to_mutate\s*=\s*(?P<value>.+)$", re.MULTILINE)


def _format_array(paths: list[str]) -> str:
    quoted = ", ".join(json.dumps(p) for p in paths)
    return f"[{quoted}]"


def _value_is_multiline(value: str) -> bool:
    stripped = value.strip()
    if not stripped.startswith("["):
        return False
    depth = 0
    for ch in stripped:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return False
    return True


def _mutmut_slice(text: str) -> tuple[int, int] | None:
    header = _MUTMUT_HEADER.search(text)
    if header is None:
        return None
    body_start = header.end()
    nxt = _NEXT_HEADER.search(text, body_start)
    body_end = nxt.start() if nxt else len(text)
    return body_start, body_end


def _rewrite(text: str, new_paths: list[str]) -> str:
    """Return ``text`` with ``paths_to_mutate`` set to ``new_paths``. Appends block if absent."""
    slice_range = _mutmut_slice(text)
    new_array = _format_array(new_paths)
    if slice_range is None:
        suffix = "" if text.endswith("\n") else "\n"
        return f"{text}{suffix}\n[tool.mutmut]\npaths_to_mutate = {new_array}\n"
    body_start, body_end = slice_range
    body = text[body_start:body_end]
    match = _PATHS_LINE.search(body)
    if match is None:
        insert = f"paths_to_mutate = {new_array}\n"
        prefix = "" if body.startswith("\n") else "\n"
        return text[:body_start] + prefix + insert + body.lstrip("\n") + text[body_end:]
    if _value_is_multiline(match.group("value")):
        raise ValueError(
            "patched_mutmut_paths: multi-line `paths_to_mutate` arrays are not supported; "
            "rewrite as a single line in pyproject.toml."
        )
    replaced = body[: match.start()] + f"paths_to_mutate = {new_array}" + body[match.end() :]
    return text[:body_start] + replaced + text[body_end:]


def _atomic_write(path: Path, data: bytes) -> None:
    directory = path.parent
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(directory))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        with suppress(FileNotFoundError):
            Path(tmp_name).chmod(path.stat().st_mode)
        Path(tmp_name).replace(path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


@contextmanager
def patched_mutmut_paths(pyproject_path: Path, new_paths: list[str]) -> Iterator[None]:
    """Temporarily set ``[tool.mutmut].paths_to_mutate`` to ``new_paths``.

    Reads the file once into memory, writes the patched bytes via atomic rename,
    and restores the original bytes on exit — including on SIGTERM/SIGINT or
    interpreter shutdown mid-``with``.
    """
    original = pyproject_path.read_bytes()
    patched = _rewrite(original.decode("utf-8"), new_paths).encode("utf-8")

    restored = False

    def _restore() -> None:
        nonlocal restored
        if restored:
            return
        restored = True
        _atomic_write(pyproject_path, original)

    prev_sigterm = signal.getsignal(signal.SIGTERM)
    prev_sigint = signal.getsignal(signal.SIGINT)

    def _handler(signum: int, frame: FrameType | None) -> None:
        _restore()
        prev = prev_sigterm if signum == signal.SIGTERM else prev_sigint
        if callable(prev):
            prev(signum, frame)
        else:
            signal.signal(signum, prev)
            os.kill(os.getpid(), signum)

    installed_signals = False
    try:
        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)
        installed_signals = True
    except ValueError:
        # signal.signal() only works on the main thread — fall through without handlers.
        pass

    atexit.register(_restore)
    _atomic_write(pyproject_path, patched)
    try:
        yield
    finally:
        try:
            _restore()
        finally:
            atexit.unregister(_restore)
            if installed_signals:
                signal.signal(signal.SIGTERM, prev_sigterm)
                signal.signal(signal.SIGINT, prev_sigint)
