"""Local-only storage for crash payloads + 30-day fingerprint dedup.

All writes are atomic (``tempfile.NamedTemporaryFile`` + :func:`os.replace`) so
a crash mid-write never leaves a half-written file readable to a subsequent
run. Files land mode 0600 inside a mode 0700 directory under the user's cache
root; nothing here ever leaves the machine.

``XDG_CACHE_HOME`` is honored on every platform — Linux convention, but we
also use it as the macOS cache override hook so tests can isolate via
``monkeypatch.setenv``.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

_DEDUP_FILE = "dedup.json"
_THIRTY_DAYS_SECONDS = 30 * 86400


def cache_dir() -> Path:
    """Return ``<XDG_CACHE_HOME or ~/.cache>/interlocks/crashes``, mode 0700.

    Creates the directory chain if missing. Parent directories may inherit the
    process umask; the final ``crashes`` directory is forced to 0700 so that
    even if the umask is loose, captured payloads stay user-readable only.
    """
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    target = Path(base) / "interlocks" / "crashes"
    target.mkdir(parents=True, exist_ok=True)
    # mkdir respects umask; chmod the final dir explicitly to guarantee 0700.
    Path(target).chmod(0o700)
    return target


def _atomic_write_text(target: Path, body: str, *, prefix: str) -> None:
    """Write ``body`` to ``target`` atomically with mode 0600.

    The temp file is created in the same directory as ``target`` so
    :func:`os.replace` is guaranteed atomic (same filesystem). On any failure
    after the temp file is created we unlink it, never the target.
    """
    directory = target.parent
    # delete=False because we manage the lifecycle manually: on success we
    # os.replace it onto the target; on failure we unlink the leftover.
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(directory),
        prefix=prefix,
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(body)
        tmp.flush()
        os.fsync(tmp.fileno())
    try:
        tmp_path.chmod(0o600)
        tmp_path.replace(target)
    except BaseException:
        # Best-effort cleanup so a failed write does not leave a stray .tmp.
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()
        raise


def write_crash(payload: Mapping[str, Any]) -> Path:
    """Atomically write ``payload`` to ``<cache_dir>/<fingerprint>.json``.

    Raises :class:`ValueError` if ``payload`` lacks a ``"fingerprint"`` key.
    """
    fingerprint = payload.get("fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise ValueError("payload['fingerprint'] is required and must be a non-empty string")

    target = cache_dir() / f"{fingerprint}.json"
    body = json.dumps(dict(payload), sort_keys=True, indent=2)
    _atomic_write_text(target, body, prefix=f".{fingerprint}.")
    return target


def _read_dedup(directory: Path) -> dict[str, float]:
    """Load ``dedup.json``; missing or corrupt → empty dict, never raise."""
    # FileNotFoundError ⊂ OSError; json.JSONDecodeError ⊂ ValueError.
    try:
        raw = (directory / _DEDUP_FILE).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    # Only keep entries that match the schema; drop the rest silently.
    return {
        key: float(value)
        for key, value in data.items()
        if isinstance(key, str) and isinstance(value, (int, float))
    }


def should_suppress_transport(fingerprint: str, *, now: float) -> bool:
    """Return True iff this fingerprint was last seen within 30 days of ``now``.

    Missing or corrupt ``dedup.json`` is treated as "never seen" — we never
    raise here because the crash boundary's invariant is that the reporter
    must not itself blow up the user's command.
    """
    directory = cache_dir()
    data = _read_dedup(directory)
    last_seen = data.get(fingerprint)
    if last_seen is None:
        return False
    return (now - last_seen) < _THIRTY_DAYS_SECONDS


def record_seen(fingerprint: str, *, now: float) -> None:
    """Atomically update ``dedup.json`` so ``data[fingerprint] = now``.

    A corrupt existing file is treated as empty and overwritten with a fresh
    single-entry mapping; we prefer "lose old dedup history" over "refuse to
    record and keep spamming the user with the same crash URL".
    """
    directory = cache_dir()
    data = _read_dedup(directory)
    data[fingerprint] = now
    body = json.dumps(data, sort_keys=True, indent=2)
    _atomic_write_text(directory / _DEDUP_FILE, body, prefix=f".{_DEDUP_FILE}.")
