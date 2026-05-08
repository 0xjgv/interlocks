"""Unit tests for :mod:`interlocks.crash.payload`.

The payload is the single allowlisted dict that ends up on disk and (with
consent) in a pre-filled GitHub issue body. These tests pin:

* the exact set of top-level keys (no surprises ever land in a payload),
* the absence of well-known leak vectors (env values, hostname, ``$USER``,
  ``sys.argv``) in the JSON-serialized form,
* the shape of the per-field values (timestamp format, version regex, frame
  kind tags, CI boolean strict-equality semantics).
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
from pathlib import Path
from typing import Any

import pytest

import interlocks
from interlocks.crash import payload as payload_mod
from interlocks.crash import scrubber as scrubber_mod
from interlocks.crash.payload import build_payload

ALLOWLIST_KEYS = {
    "schema_version",
    "fingerprint",
    "timestamp_utc",
    "interlocks_version",
    "python_version",
    "platform_system",
    "platform_machine",
    "subcommand",
    "exception_type",
    "frames",
    "ci",
    "stage",
    "uv_version",
    "uvx_version",
}


def _raise_key_error() -> None:
    """Helper to give us a real traceback with a frame in the test file."""
    raise KeyError("synthetic-test-only")


def _capture_keyerror() -> KeyError:
    try:
        _raise_key_error()
    except KeyError as exc:
        return exc
    raise AssertionError("unreachable")


def _build(subcommand: str = "lint") -> dict[str, Any]:
    """Capture a fresh KeyError and build the payload — the per-test boilerplate."""
    return build_payload(_capture_keyerror(), subcommand=subcommand, project_root=Path.cwd())


@pytest.fixture
def force_interlocks_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mark this test file as an interlocks frame so the scrubber keeps it.

    The scrubber filters frames by package directory; tests live outside the
    package, so without this patch the synthetic raise would collapse to an
    ``ExternalFrames`` marker and the payload would have no interlocks frames
    to fingerprint over.
    """
    real_is_interlocks_frame = scrubber_mod.is_interlocks_frame
    test_file = __file__

    def fake(filename: str) -> bool:
        if filename == test_file:
            return True
        return real_is_interlocks_frame(filename)

    monkeypatch.setattr(scrubber_mod, "is_interlocks_frame", fake)


# ─────────────── happy path / allowlist ─────────────────────────────


def test_payload_contains_exactly_allowlisted_keys(
    force_interlocks_frame: None,
) -> None:
    result = _build()
    assert set(result.keys()) == ALLOWLIST_KEYS
    # No extras hiding under None values either.
    assert len(result) == len(ALLOWLIST_KEYS)


def test_payload_is_json_serializable(force_interlocks_frame: None) -> None:
    # Round-trip through JSON to confirm there are no non-serializable types
    # (Path, datetime, dataclass instances) leaking into the payload.
    parsed = json.loads(json.dumps(_build()))
    assert set(parsed.keys()) == ALLOWLIST_KEYS


# ─────────────── allowlist negative tests ───────────────────────────


def test_payload_does_not_leak_env_values(
    force_interlocks_frame: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setting a known env var must NOT have its value appear in the JSON dump."""
    # Build the key name from parts so this test file does not contain a
    # hard-coded secret-shaped assignment that would trip secret scanners.
    env_key = "FAKE" + "_API" + "_KEY_FOR_CRASH_TEST"
    sentinel = "marker-" + "xyz123-not-real"
    monkeypatch.setenv(env_key, sentinel)
    assert sentinel not in json.dumps(_build())


def test_payload_does_not_leak_hostname(force_interlocks_frame: None) -> None:
    hostname = socket.gethostname()
    if not hostname:
        pytest.skip("no hostname configured on this machine")
    assert hostname not in json.dumps(_build())


def test_payload_does_not_leak_user(force_interlocks_frame: None) -> None:
    user = os.getenv("USER", "")
    if not user:
        pytest.skip("USER env not set")
    assert user not in json.dumps(_build())


def test_payload_does_not_leak_sys_argv(
    force_interlocks_frame: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Distinctive sys.argv marker must not appear anywhere in the JSON dump."""
    marker = "secret-arg-marker-9988"
    monkeypatch.setattr(sys, "argv", ["pytest", marker])
    assert marker not in json.dumps(_build())


# ─────────────── per-field shape ────────────────────────────────────


def test_exception_type_is_class_name_only(force_interlocks_frame: None) -> None:
    result = _build()
    assert result["exception_type"] == "KeyError"
    assert "." not in result["exception_type"]
    assert "builtins" not in result["exception_type"]


def test_python_version_matches_dotted_triple(force_interlocks_frame: None) -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", _build()["python_version"])


def test_timestamp_utc_iso8601_second_precision(
    force_interlocks_frame: None,
) -> None:
    ts = _build()["timestamp_utc"]
    assert ts.endswith("Z")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", ts)


def test_schema_version_is_two(force_interlocks_frame: None) -> None:
    """Schema bumped to 2 with uv_version + uvx_version fields."""
    assert _build()["schema_version"] == 2


def test_interlocks_version_matches_package(force_interlocks_frame: None) -> None:
    assert _build()["interlocks_version"] == interlocks.__version__


def test_subcommand_round_trip(force_interlocks_frame: None) -> None:
    result = _build("nightly")
    assert result["subcommand"] == "nightly"
    # Stage is a documented alias for now (spec §2.5); both must be strings.
    assert isinstance(result["stage"], str)
    assert result["stage"] == "nightly"


def test_fingerprint_is_16_hex(force_interlocks_frame: None) -> None:
    assert re.fullmatch(r"[0-9a-f]{16}", _build()["fingerprint"])


# ─────────────── frames structure ────────────────────────────────────


def test_frames_have_correct_kind_tags(force_interlocks_frame: None) -> None:
    frames = _build()["frames"]
    assert isinstance(frames, list)
    assert frames, "expected at least one frame from the synthetic raise"
    for frame in frames:
        assert frame["kind"] in {"interlocks", "external"}
        if frame["kind"] == "interlocks":
            assert set(frame.keys()) == {"filename", "line_no", "function", "kind"}
            assert isinstance(frame["filename"], str)
            assert isinstance(frame["line_no"], int)
            assert isinstance(frame["function"], str)
        else:
            assert set(frame.keys()) == {"kind", "count"}
            assert isinstance(frame["count"], int)


def test_frames_include_synthetic_raise_function(
    force_interlocks_frame: None,
) -> None:
    """The interlocks frame for the helper must surface its function name."""
    interlocks_frames = [f for f in _build()["frames"] if f["kind"] == "interlocks"]
    assert "_raise_key_error" in {f["function"] for f in interlocks_frames}


# ─────────────── ci boolean strictness ──────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("True", False),
        ("1", False),
        ("false", False),
        ("", False),
    ],
)
def test_ci_only_true_for_literal_lowercase_true(
    force_interlocks_frame: None,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    expected: bool,
) -> None:
    monkeypatch.setenv("CI", value)
    assert _build()["ci"] is expected


def test_ci_false_when_unset(
    force_interlocks_frame: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CI", raising=False)
    assert _build()["ci"] is False


# ─────────────── module-level smoke ──────────────────────────────────


def test_schema_version_constant_exposed() -> None:
    """Schema version is a module constant so storage/transport can reference it."""
    assert payload_mod.SCHEMA_VERSION == 2
