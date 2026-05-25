"""Generated-input checks for version JSON helpers."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from interlocks.tasks.version import _version_payload


@given(version=st.text(max_size=80))
def test_version_payload_preserves_version_string(version: str) -> None:
    assert _version_payload(version) == {
        "command": "version",
        "passed": True,
        "version": version,
    }
