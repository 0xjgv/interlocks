"""Property tests for crash fingerprinting and traceback scrubbing."""

from __future__ import annotations

import json
import math
import os
import re
from itertools import pairwise
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from urllib.parse import quote, unquote

from hypothesis import given
from hypothesis import strategies as st

import interlocks
from interlocks.crash.fingerprint import compute
from interlocks.crash.scrubber import (
    ExternalFrames,
    ScrubbedFrame,
    is_interlocks_frame,
    normalize_traceback,
    scrub_path,
)
from interlocks.crash.storage import (
    _DEDUP_FILE,
    _THIRTY_DAYS_SECONDS,
    _read_dedup,
    should_suppress_transport,
)
from interlocks.crash.transport import (
    _BODY_ENCODED_CAP,
    _encode_body_within_cap,
    _format_frame,
    _render_body,
)

_HEX16 = re.compile(r"^[0-9a-f]{16}$")
_SEGMENTS = st.from_regex(r"[A-Za-z0-9_.-]{1,20}", fullmatch=True)
_PATH_SEGMENTS = _SEGMENTS.filter(lambda value: value not in {".", ".."})
_FRAME_PAIRS = st.lists(st.tuples(st.text(max_size=30), st.text(max_size=30)), max_size=20)
_SAFE_TEXT = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=80)
_FINITE_TS = st.floats(
    min_value=-10_000_000,
    max_value=10_000_000,
    allow_nan=False,
    allow_infinity=False,
)
_JSON_VALUE = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-1_000, max_value=1_000),
    st.floats(allow_nan=True, allow_infinity=True, width=32),
    _SAFE_TEXT,
)


def _fake_tb_chain(frames: list[tuple[str, int, str]]) -> Any:
    head: Any = None
    for filename, lineno, name in reversed(frames):
        code = SimpleNamespace(co_filename=filename, co_name=name)
        frame = SimpleNamespace(f_code=code)
        head = SimpleNamespace(tb_frame=frame, tb_lineno=lineno, tb_next=head)
    return head


@given(frames=_FRAME_PAIRS, exception_type=st.text(max_size=50))
def test_crash_fingerprint_is_stable_hex(
    frames: list[tuple[str, str]],
    exception_type: str,
) -> None:
    first = compute(frames, exception_type)
    second = compute(frames, exception_type)

    assert first == second
    assert _HEX16.fullmatch(first)


@given(user=_SEGMENTS, tail=st.lists(_SEGMENTS, max_size=5))
def test_scrub_path_redacts_macos_user_segment(user: str, tail: list[str]) -> None:
    raw = "/".join(["/Users", user, *tail])

    with patch.object(Path, "home", staticmethod(lambda: Path("/Users/current"))):
        scrubbed = scrub_path(raw, project_root=None)

    if user == "current":
        assert scrubbed.startswith("~")
    else:
        assert scrubbed.startswith("/Users/<user>")
    assert not scrubbed.startswith(f"/Users/{user}")


@given(user=_SEGMENTS, tail=st.lists(_SEGMENTS, max_size=5))
def test_scrub_path_redacts_linux_user_segment(user: str, tail: list[str]) -> None:
    raw = "/".join(["/home", user, *tail])

    with patch.object(Path, "home", staticmethod(lambda: Path("/Users/current"))):
        scrubbed = scrub_path(raw, project_root=None)

    assert scrubbed.startswith("/home/<user>")
    assert not scrubbed.startswith(f"/home/{user}")


@given(kinds=st.lists(st.booleans(), max_size=30))
def test_normalize_traceback_preserves_interlocks_count_and_collapses_externals(
    kinds: list[bool],
) -> None:
    pkg_root = Path(interlocks.__file__).resolve().parent
    frames = [
        (
            str(pkg_root / f"generated_{index}.py")
            if is_interlocks
            else f"/usr/lib/python/generated_{index}.py",
            index + 1,
            f"f_{index}",
        )
        for index, is_interlocks in enumerate(kinds)
    ]

    normalized = normalize_traceback(_fake_tb_chain(frames), project_root=None)

    scrubbed = [item for item in normalized if isinstance(item, ScrubbedFrame)]
    external = [item for item in normalized if isinstance(item, ExternalFrames)]
    assert len(scrubbed) == sum(kinds)
    assert sum(item.count for item in external) == len(kinds) - sum(kinds)
    assert not any(
        isinstance(left, ExternalFrames) and isinstance(right, ExternalFrames)
        for left, right in pairwise(normalized)
    )


@given(tail=st.lists(_PATH_SEGMENTS, min_size=1, max_size=5))
def test_is_interlocks_frame_matches_installed_package_prefix(tail: list[str]) -> None:
    pkg_root = Path(interlocks.__file__).resolve().parent
    filename = str(pkg_root.joinpath(*tail))

    assert is_interlocks_frame(filename)


@given(tail=st.lists(_PATH_SEGMENTS, min_size=1, max_size=5))
def test_is_interlocks_frame_rejects_sibling_prefixes(tail: list[str]) -> None:
    pkg_root = Path(interlocks.__file__).resolve().parent
    filename = str(pkg_root.parent.joinpath(f"{pkg_root.name}_other", *tail))

    assert not is_interlocks_frame(filename)


@given(rows=st.dictionaries(_SAFE_TEXT, _JSON_VALUE, max_size=20))
def test_read_dedup_keeps_only_finite_numeric_timestamps(rows: dict[str, object]) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        (root / _DEDUP_FILE).write_text(json.dumps(rows), encoding="utf-8")

        loaded = _read_dedup(root)

    expected: dict[str, float] = {}
    for key, value in rows.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        timestamp = float(value)
        if math.isfinite(timestamp):
            expected[key] = timestamp
    assert loaded == expected


@given(
    fingerprint=_SEGMENTS,
    include_entry=st.booleans(),
    last_seen=_FINITE_TS,
    now=_FINITE_TS,
)
def test_should_suppress_transport_matches_thirty_day_dedup_window(
    fingerprint: str,
    include_entry: bool,
    last_seen: float,
    now: float,
) -> None:
    with TemporaryDirectory() as raw_root, patch.dict(os.environ, {"XDG_CACHE_HOME": raw_root}):
        directory = Path(raw_root) / "interlocks" / "crashes"
        directory.mkdir(parents=True)
        payload = {fingerprint: last_seen} if include_entry else {}
        (directory / _DEDUP_FILE).write_text(json.dumps(payload), encoding="utf-8")

        suppressed = should_suppress_transport(fingerprint, now=now)

    assert suppressed is (include_entry and (now - last_seen) < _THIRTY_DAYS_SECONDS)


@given(
    size=st.integers(min_value=_BODY_ENCODED_CAP + 1, max_value=_BODY_ENCODED_CAP * 3),
    tail=st.lists(_SEGMENTS, max_size=500),
)
def test_encode_body_within_cap_never_exceeds_encoded_limit(size: int, tail: list[str]) -> None:
    local_path = Path("/", *tail) if tail else Path("/var/empty/interlocks-crash.json")

    encoded = _encode_body_within_cap("x" * size, local_path=local_path)
    decoded = unquote(encoded)

    assert len(encoded) <= _BODY_ENCODED_CAP
    assert decoded.endswith((f"(full payload at {local_path})", "(truncated)"))


@given(body=st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=200))
def test_encode_body_within_cap_preserves_small_bodies(body: str) -> None:
    encoded = _encode_body_within_cap(body, local_path=None)

    if len(quote(body, safe="")) <= _BODY_ENCODED_CAP:
        assert unquote(encoded) == body


@given(
    filename=_SAFE_TEXT,
    line_no=st.integers(),
    function=_SAFE_TEXT,
)
def test_format_frame_formats_interlocks_frames(
    filename: str, line_no: int, function: str
) -> None:
    assert (
        _format_frame({
            "kind": "interlocks",
            "filename": filename,
            "line_no": line_no,
            "function": function,
        })
        == f"{filename}:{line_no} {function}"
    )


@given(count=st.one_of(st.integers(), _SAFE_TEXT))
def test_format_frame_formats_external_counts(count: object) -> None:
    assert _format_frame({"kind": "external", "count": count}) == f"<external frames: {count}>"


@given(extra_value=_SEGMENTS.map(lambda value: f"UNALLOWLISTED_{value}"))
def test_render_body_ignores_unallowlisted_payload_fields(extra_value: str) -> None:
    body = _render_body({
        "exception_type": "RuntimeError",
        "fingerprint": "abc123",
        "unallowlisted": extra_value,
        "frames": [],
    })

    assert "RuntimeError" in body
    assert "abc123" in body
    assert extra_value not in body
