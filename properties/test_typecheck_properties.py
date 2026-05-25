"""Generated-input checks for typecheck JSON helpers."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from interlocks.tasks.typecheck import _typecheck_skip_payload


@given(reason=st.text(), next_action=st.text())
def test_typecheck_skip_payload_is_stable(reason: str, next_action: str) -> None:
    payload = _typecheck_skip_payload(reason=reason, next_action=next_action)

    assert payload == {
        "command": "typecheck",
        "passed": True,
        "status": "skipped",
        "reason": reason,
        "next_actions": [next_action],
    }
