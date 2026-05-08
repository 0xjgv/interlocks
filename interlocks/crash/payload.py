"""Allowlisted crash-report payload assembly.

The boundary captures an exception; this module turns it into the strict,
schema-versioned dict that ends up on disk and (with consent) in a pre-filled
GitHub issue body. Every key in the returned dict is enumerated below — there
is no ``**kwargs`` path, no env spread, no locals dump. If a future reviewer
wants to add a field, they edit this file and the allowlist test in
``tests/test_crash_payload.py``; nothing else.

What is intentionally NOT in the payload:

* frame locals / repr of frame objects
* ``os.environ`` values, ``.env`` contents, raw ``HOME`` or ``USER``
* hostname, full uname, network IDs, git remotes
* full ``sys.argv`` (we record only the resolved subcommand passed in)
* subprocess stdout/stderr, source snippets

Path redaction is delegated to :mod:`interlocks.crash.scrubber`; this module
does not call ``scrub_path`` directly. The frame list it ships is whatever
``normalize_traceback`` returns, after a ``ScrubbedFrame``/``ExternalFrames``
to-dict translation that keeps the on-disk schema flat.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import interlocks
from interlocks.crash.fingerprint import compute as compute_fingerprint
from interlocks.crash.scrubber import (
    ScrubbedFrame,
    normalize_traceback,
)

if TYPE_CHECKING:
    from pathlib import Path

SCHEMA_VERSION = 2


def _binary_version(name: str) -> str | None:
    """Return ``<name> --version`` output's first line, or ``None`` if unavailable.

    Best-effort: missing binary, non-zero exit, or any subprocess hiccup yields
    ``None`` — crash reporting must never fail because uv is missing.
    """
    if shutil.which(name) is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 (trusted bin lookup via shutil.which)
            [name, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stdout or result.stderr or "").splitlines()
    return output[0].strip() if output else None


def build_payload(
    exc: BaseException,
    *,
    subcommand: str,
    project_root: Path | None,
) -> dict[str, Any]:
    """Return the on-disk crash payload for ``exc``.

    The dict contains exactly twelve keys (see ``SCHEMA_VERSION``-pinned
    contract in the module docstring); callers may not add more without
    updating the allowlist test.
    """
    scrubbed = normalize_traceback(exc.__traceback__, project_root)
    exception_type = type(exc).__name__

    # Fingerprint input: only the interlocks-frame (filename, function) pairs.
    # ExternalFrames markers carry no per-bug identity — including their count
    # would tie fingerprints to incidental third-party stack depth.
    fingerprint_pairs: list[tuple[str, str]] = [
        (item.filename, item.function_name) for item in scrubbed if isinstance(item, ScrubbedFrame)
    ]
    fingerprint = compute_fingerprint(fingerprint_pairs, exception_type)

    frames: list[dict[str, Any]] = []
    for item in scrubbed:
        if isinstance(item, ScrubbedFrame):
            frames.append({
                "filename": item.filename,
                "line_no": item.line_no,
                "function": item.function_name,
                "kind": "interlocks",
            })
        else:  # ExternalFrames
            frames.append({"kind": "external", "count": item.count})

    timestamp_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    return {
        "schema_version": SCHEMA_VERSION,
        "fingerprint": fingerprint,
        "timestamp_utc": timestamp_utc,
        "interlocks_version": interlocks.__version__,
        "python_version": python_version,
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "subcommand": subcommand,
        "exception_type": exception_type,
        "frames": frames,
        "ci": os.environ.get("CI") == "true",
        "stage": subcommand,
        # Tool dispatch chain — every gate runs through ``uvx``/``uv run``;
        # capturing the resolved binary versions makes "tool X failed at version
        # Y" reports actionable when uv itself ships a regression.
        "uv_version": _binary_version("uv"),
        "uvx_version": _binary_version("uvx"),
    }
