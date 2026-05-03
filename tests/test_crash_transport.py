"""Unit tests for ``interlocks.crash.transport``.

These tests pin the behavioral contract of ``BrowserTransport.submit``:

* URL shape — destination is the caller-supplied repo, body is rendered as
  Markdown, ``labels=crash-report`` is on the query string.
* No network — we introspect the module source to assert no socket /
  ``urllib.request`` / ``http.client`` imports, since interlocks itself MUST
  NOT make HTTP requests on its own.
* Stderr is the contract — after reporting is accepted, the URL prints exactly
  once regardless of whether ``webbrowser.open`` succeeds, fails, or raises.
* Oversized payloads truncate cleanly with a pointer to the local file.
"""

from __future__ import annotations

import inspect
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import pytest

from interlocks.crash import transport as transport_mod
from interlocks.crash.transport import BrowserTransport

_REPO = "0xjgv/interlocks"

_BASE_PAYLOAD: dict[str, Any] = {
    "schema_version": 1,
    "fingerprint": "deadbeefcafebabe",
    "timestamp_utc": "2026-04-30T12:34:56Z",
    "interlocks_version": "0.42.0",
    "python_version": "3.13.1",
    "platform_system": "Darwin",
    "platform_machine": "arm64",
    "subcommand": "check",
    "exception_type": "RuntimeError",
    "frames": [
        {
            "kind": "interlocks",
            "filename": "interlocks/cli.py",
            "line_no": 370,
            "function": "main",
        },
        {"kind": "external", "count": 3},
        {
            "kind": "interlocks",
            "filename": "interlocks/runner.py",
            "line_no": 153,
            "function": "_dispatch",
        },
    ],
    "ci": False,
    "stage": "check",
}


def _silent_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default browser stub: no-op that reports failure to open."""
    monkeypatch.setattr(webbrowser, "open", lambda *a, **kw: False)


def _decode_body(url: str) -> str:
    """Pull the ``body=`` query parameter out of ``url`` and unquote it."""
    query = urlsplit(url).query
    for part in query.split("&"):
        if part.startswith("body="):
            return unquote(part[len("body=") :])
    raise AssertionError(f"no body= parameter in url: {url}")


def test_url_starts_with_repo_issues_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _silent_browser(monkeypatch)
    url = BrowserTransport.submit(_BASE_PAYLOAD, repo=_REPO)
    assert url.startswith("https://github.com/0xjgv/interlocks/issues/new?")
    assert "labels=crash-report" in url
    capsys.readouterr()  # drain so other tests start clean


def test_body_contains_exception_fingerprint_and_versions(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _silent_browser(monkeypatch)
    url = BrowserTransport.submit(_BASE_PAYLOAD, repo=_REPO)
    body = _decode_body(url)

    assert "RuntimeError" in body
    assert "deadbeefcafebabe" in body
    assert "0.42.0" in body
    assert "3.13.1" in body
    assert "Please add what you were trying to do before submitting." in body
    capsys.readouterr()


def test_decoded_body_preserves_markdown_header(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _silent_browser(monkeypatch)
    url = BrowserTransport.submit(_BASE_PAYLOAD, repo=_REPO)
    body = _decode_body(url)
    # The "## Crash report" header proves that newline + hashes survived
    # the encode/decode round trip — i.e. we built the body before
    # quoting, not after.
    assert "## Crash report" in body
    assert "## Frames" in body
    capsys.readouterr()


def test_no_network_imports_in_module_source() -> None:
    """Lint backstop: interlocks itself must not open a network socket.

    Reading the module source (rather than its compiled bytecode) catches
    both ``import X`` and ``from X import Y`` shapes, which is what we
    actually care about — the module attribute table would not.
    """
    src = inspect.getsource(transport_mod)
    assert "import socket" not in src
    assert "urllib.request" not in src
    assert "http.client" not in src
    assert "import requests" not in src
    assert "import httpx" not in src


def test_oversized_body_truncates_with_local_path_pointer(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _silent_browser(monkeypatch)

    # 200 frames at ~80-char filenames will blow well past the 7800-char
    # encoded cap. Each interlocks frame line is roughly 100 chars before
    # encoding, and percent-encoding inflates non-ASCII-safe characters
    # (slashes, colons, spaces) by 2-3x.
    long_filename_prefix = "interlocks/" + "x" * 60 + "/"
    huge_frames: list[dict[str, Any]] = [
        {
            "kind": "interlocks",
            "filename": f"{long_filename_prefix}module_{i:03d}.py",
            "line_no": i,
            "function": f"function_with_a_reasonably_long_name_{i:03d}",
        }
        for i in range(200)
    ]
    payload = {**_BASE_PAYLOAD, "frames": huge_frames}
    local_path = Path("/var/empty/foo.json")

    url = BrowserTransport.submit(payload, repo=_REPO, local_path=local_path)
    body_encoded = urlsplit(url).query.split("&body=", 1)[1].split("&", 1)[0]
    # Cap is on the encoded body segment alone.
    assert len(body_encoded) <= 7800

    decoded = _decode_body(url)
    assert decoded.endswith("(full payload at /var/empty/foo.json)")
    capsys.readouterr()


def test_url_printed_to_stderr_exactly_once_when_browser_returns_false(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(webbrowser, "open", lambda *a, **kw: False)
    url = BrowserTransport.submit(_BASE_PAYLOAD, repo=_REPO)

    captured = capsys.readouterr()
    assert captured.err.count(url) == 1
    assert "Open this pre-filled GitHub issue" in captured.err
    assert "Review the issue in your browser before submitting it." in captured.err


def test_browser_open_raising_does_not_propagate(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _raise(*_args: object, **_kwargs: object) -> bool:
        raise RuntimeError("no display")

    monkeypatch.setattr(webbrowser, "open", _raise)
    # Must not raise; URL must still come back.
    url = BrowserTransport.submit(_BASE_PAYLOAD, repo=_REPO)
    assert url.startswith("https://github.com/0xjgv/interlocks/issues/new?")

    captured = capsys.readouterr()
    assert url in captured.err


def test_url_printed_in_both_headless_and_success_browser_paths(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Headless: open returns False (no browser available).
    monkeypatch.setattr(webbrowser, "open", lambda *a, **kw: False)
    headless_url = BrowserTransport.submit(_BASE_PAYLOAD, repo=_REPO)
    headless_err = capsys.readouterr().err
    assert headless_url in headless_err

    # Success: open returns True (browser launched).
    monkeypatch.setattr(webbrowser, "open", lambda *a, **kw: True)
    success_url = BrowserTransport.submit(_BASE_PAYLOAD, repo=_REPO)
    success_err = capsys.readouterr().err
    assert success_url in success_err
