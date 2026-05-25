"""Generated-input checks for architecture-gate JSON helpers."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from interlocks.tasks.arch import _arch_skip_payload


@given(reason=st.text())
def test_arch_skip_payload_is_stable(reason: str) -> None:
    payload = _arch_skip_payload(reason)

    assert payload == {
        "command": "arch",
        "passed": True,
        "status": "skipped",
        "reason": reason,
        "next_actions": [
            "Add import-linter contracts or make the configured source and test dirs packages."
        ],
    }
