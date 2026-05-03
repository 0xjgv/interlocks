"""``CrashBoundary``: classify CLI exceptions into re-raise / user-error / crash.

The boundary is the single place where interlocks-internal bugs are routed.

* Re-raises ``SystemExit`` / ``KeyboardInterrupt`` / ``GeneratorExit`` unchanged
  — subprocess gate failures already exit via ``sys.exit(rc)`` and bypass any
  ``except Exception``.
* Catches :class:`~interlocks.config.InterlockUserError`, prints a clean
  ``interlocks: <message>`` line to stderr, and exits 2 without capturing.
* For any other ``Exception`` originating inside the ``interlocks/`` package,
  builds a redacted payload, writes it to ``~/.cache/interlocks/crashes/``,
  consults the dedup window, asks the user whether to report, and (when
  accepted) opens a pre-filled GitHub Issues URL via the browser. The original
  exception is always re-raised so Python emits its canonical traceback and
  exits 1.

Invariant I6: a bug inside the crash reporter MUST NOT mask the original
exception. Capture / transport are wrapped in ``_safely`` which logs a single
``(crash reporter failed: ...)`` line and swallows.
"""

from __future__ import annotations

import os
import sys
import time
from typing import TYPE_CHECKING

from interlocks.config import InterlockUserError, load_config
from interlocks.crash.payload import build_payload
from interlocks.crash.prompt import prompt_for_report
from interlocks.crash.scrubber import is_interlocks_frame
from interlocks.crash.storage import (
    record_seen,
    should_suppress_transport,
    write_crash,
)
from interlocks.crash.transport import BrowserTransport

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import TracebackType

    from interlocks.config import InterlockConfig

# Test-only injection point. Kept inside the boundary so acceptance tests can
# trigger a crash from outside the process via env var without depending on
# a real bug in interlocks. Inert when unset.
_INJECT_ENV = "INTERLOCKS_CRASH_INJECT"

# Repo target for pre-filled issue URLs. Open Question #1 in the design doc
# pinned this to the homepage URL in pyproject.toml.
_REPO = "0xjgv/interlocks"


class CrashBoundary:
    """Context manager that classifies and routes exceptions at the CLI surface.

    Usage::

        boundary = CrashBoundary(subcommand="check")
        with boundary:
            boundary.maybe_inject_for_test()
            TASKS["check"][0]()

    The constructor takes the resolved subcommand name so the captured payload
    can record it (no ``sys.argv`` ever reaches the payload).
    """

    def __init__(self, *, subcommand: str) -> None:
        self.subcommand = subcommand

    def __enter__(self) -> CrashBoundary:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if exc is None:
            return False
        if isinstance(exc, (SystemExit, KeyboardInterrupt, GeneratorExit)):
            return False
        if isinstance(exc, InterlockUserError):
            print(f"interlocks: {exc}", file=sys.stderr)
            sys.exit(2)
        if not _is_interlocks_exception(exc):
            return False
        _safely(lambda: _capture_and_transport(exc, self.subcommand))
        return False

    def maybe_inject_for_test(self) -> None:
        """Raise the synthetic ``RuntimeError`` when ``INTERLOCKS_CRASH_INJECT`` matches.

        Called from inside the ``with`` block so the injected exception goes
        through ``__exit__``. Inert outside tests.
        """
        _maybe_inject(self.subcommand)


def _maybe_inject(subcommand: str) -> None:
    target = os.environ.get(_INJECT_ENV)
    if target and target == subcommand:
        raise RuntimeError("injected for crash boundary test")


def _is_interlocks_exception(exc: BaseException) -> bool:
    """True when ``exc`` originated inside the ``interlocks/`` package.

    We walk the traceback and check whether any frame's filename lives under
    the package directory. A traceback with no interlocks frames at all means
    the bug is in user code or a third-party caller; the boundary stays out.
    """
    tb = exc.__traceback__
    while tb is not None:
        if is_interlocks_frame(tb.tb_frame.f_code.co_filename):
            return True
        tb = tb.tb_next
    return False


def _capture_and_transport(exc: BaseException, subcommand: str) -> None:
    """Capture → write → dedup → prompt → transport → record-seen.

    Local capture is unconditional; reporting is gated separately. If the
    dedup window suppresses, the terminal is non-interactive, or the user
    declines, we still leave the local file on disk for forensic value.
    """
    _cfg, project_root = _safe_load_config()
    payload = build_payload(exc, subcommand=subcommand, project_root=project_root)
    local_path = write_crash(payload)
    fingerprint = payload["fingerprint"]
    now = time.time()
    if should_suppress_transport(fingerprint, now=now):
        return
    decision = prompt_for_report(local_path=local_path)
    if decision == "unavailable":
        return
    if decision == "skip":
        record_seen(fingerprint, now=now)
        return
    BrowserTransport.submit(payload, repo=_REPO, local_path=local_path)
    record_seen(fingerprint, now=now)


def _safe_load_config() -> tuple[InterlockConfig | None, Path | None]:
    """Best-effort config load. Returns ``(None, None)`` if anything fails.

    A broken ``pyproject.toml`` should never block local capture. When config
    cannot load, path scrubbing falls back to the generic rules.
    """
    try:
        cfg = load_config()
    except Exception:
        return None, None
    return cfg, cfg.project_root


def _safely(fn: Callable[[], None]) -> None:
    """Run ``fn``; never let its exception escape — the original must re-raise.

    Invariant I6: a bug inside the crash reporter MUST NOT mask the original
    exception. We log a single ``(crash reporter failed: ...)`` line and swallow.
    """
    try:
        fn()
    except Exception as exc:
        print(f"(crash reporter failed: {exc})", file=sys.stderr)
