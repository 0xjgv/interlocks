"""Browser-only transport for crash reports.

This module is the single, narrow place where interlocks turns a crash payload
into a user-visible artifact. The contract is intentionally minimal:

* Build a pre-filled GitHub Issues URL with the payload rendered as Markdown.
* Print that URL to stderr after the user accepts reporting.
* Try to open the URL in the user's default browser as a convenience, but never
  let a browser failure mask the crash or raise out of ``submit``.

Network-egress modules are forbidden in this file and enforced by a source
introspection check in ``tests/test_crash_transport.py``. interlocks NEVER
opens a network connection of its own — the user's browser does, and only
if they choose to.
"""

from __future__ import annotations

import contextlib
import sys
import webbrowser
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

# GitHub caps issue URLs at ~8 KiB before it stops pre-filling the body. We
# stay comfortably under that with a 7800-char ceiling on the *encoded* body
# segment, leaving headroom for the rest of the URL (scheme, host, path,
# title, labels). The ceiling is enforced by iterative truncation of the
# pre-encoded body string, never by chopping percent-escapes.
_BODY_ENCODED_CAP = 7800


class BrowserTransport:
    """Render a crash payload to a GitHub Issues URL and surface it locally.

    The class exposes a single ``submit`` static method by design — there is
    no instance state, no constructor, no configuration. Callers pass the
    repo string explicitly so this module never hardcodes a destination.
    """

    @staticmethod
    def submit(
        payload: Mapping[str, Any],
        *,
        repo: str,
        local_path: Path | None = None,
    ) -> str:
        """Build the issues URL, print it to stderr, try to open the browser.

        Returns the URL string. The raw URL is printed on its own line so it
        remains easy to copy from headless or browser-open-failure paths.
        Browser-open failures are swallowed — the URL on stderr is the
        contract; the browser is convenience.
        """
        title = f"interlocks crash: {payload.get('exception_type', 'Unknown')}"
        body = _render_body(payload)
        encoded_body = _encode_body_within_cap(body, local_path=local_path)
        encoded_title = quote(title, safe="")
        url = (
            f"https://github.com/{repo}/issues/new"
            f"?title={encoded_title}"
            f"&body={encoded_body}"
            f"&labels=crash-report"
        )

        print("Open this pre-filled GitHub issue to report the crash:", file=sys.stderr)
        print(url, file=sys.stderr)
        print("Review the issue in your browser before submitting it.", file=sys.stderr)

        # The URL on stderr is the contract; opening the browser is a
        # convenience that must never raise out of ``submit``.
        with contextlib.suppress(Exception):
            webbrowser.open(url, new=2)

        return url


def _encode_body_within_cap(body: str, *, local_path: Path | None) -> str:
    """URL-encode ``body``; if the encoded result exceeds the cap, truncate.

    Truncation operates on the *source* body and re-encodes after each
    shrink — chopping a percent-encoded string would yield invalid URLs by
    splitting ``%XX`` triples. We shrink the source body iteratively in
    5%-of-current-length steps, with a 1-char floor so we always make
    progress on tiny remainders.

    When truncation occurs, a tail pointer is appended to the *source* body
    before re-encoding so the rendered issue body shows the user where to
    find the full crash payload locally. Without ``local_path`` we fall
    back to a generic ``(truncated)`` marker.
    """
    encoded = quote(body, safe="")
    if len(encoded) <= _BODY_ENCODED_CAP:
        return encoded

    suffix = f"\n\n(full payload at {local_path})" if local_path is not None else "\n\n(truncated)"
    encoded_suffix_len = len(quote(suffix, safe=""))
    target_encoded = _BODY_ENCODED_CAP - encoded_suffix_len

    truncated = body
    while True:
        encoded_truncated = quote(truncated, safe="")
        if len(encoded_truncated) <= target_encoded:
            break
        shrink = max(1, len(truncated) // 20)
        truncated = truncated[: len(truncated) - shrink]

    return quote(truncated + suffix, safe="")


def _render_body(payload: Mapping[str, Any]) -> str:
    """Render the allowlisted payload fields as a Markdown issue body.

    Fields rendered: interlocks_version, python_version, platform_system,
    platform_machine, subcommand, exception_type, timestamp_utc, ci,
    fingerprint, frames. Anything else in the payload is ignored — this
    function is the schema-to-prose translator, not a generic dict dumper.
    """
    interlocks_version = payload.get("interlocks_version", "")
    python_version = payload.get("python_version", "")
    platform_system = payload.get("platform_system", "")
    platform_machine = payload.get("platform_machine", "")
    subcommand = payload.get("subcommand", "")
    exception_type = payload.get("exception_type", "")
    timestamp_utc = payload.get("timestamp_utc", "")
    ci = payload.get("ci", False)
    fingerprint = payload.get("fingerprint", "")
    frames = payload.get("frames", []) or []

    lines = [
        "## Crash report",
        "",
        "Please add what you were trying to do before submitting.",
        "",
        f"- interlocks: {interlocks_version}",
        f"- python: {python_version}",
        f"- platform: {platform_system}/{platform_machine}",
        f"- subcommand: {subcommand}",
        f"- exception: {exception_type}",
        f"- timestamp: {timestamp_utc}",
        f"- ci: {ci}",
        f"- fingerprint: {fingerprint}",
        "",
        "## Frames",
        "",
        "```",
    ]
    for frame in frames:
        lines.append(_format_frame(frame))
    lines.append("```")

    return "\n".join(lines)


def _format_frame(frame: Mapping[str, Any]) -> str:
    """Format one frame entry. Mirrors the schema in ``payload.py``."""
    kind = frame.get("kind")
    if kind == "external":
        count = frame.get("count", 0)
        return f"<external frames: {count}>"
    filename = frame.get("filename", "")
    line_no = frame.get("line_no", 0)
    function = frame.get("function", "")
    return f"{filename}:{line_no} {function}"
