"""Generated-input checks for audit JSON helpers."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from interlocks.tasks.audit import _audit_network_payload


@given(
    passed=st.booleans(),
    status=st.text(),
    elapsed=st.floats(allow_nan=False, allow_infinity=False, width=32),
    reason=st.one_of(st.none(), st.text()),
)
def test_audit_network_payload_shape_is_stable(
    passed: bool,
    status: str,
    elapsed: float,
    reason: str | None,
) -> None:
    payload = _audit_network_payload(
        passed=passed,
        status=status,
        elapsed=elapsed,
        reason=reason,
    )

    assert payload["command"] == "audit"
    assert payload["passed"] is passed
    assert payload["status"] == status
    assert payload["elapsed_seconds"] == round(elapsed, 3)
    assert ("reason" in payload) is (reason is not None)
