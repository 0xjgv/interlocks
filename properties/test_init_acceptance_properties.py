"""Generated-input checks for init-acceptance JSON helpers."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from interlocks.tasks.init_acceptance import (
    _INIT_ACCEPTANCE_NEXT_ACTIONS,
    _INIT_ACCEPTANCE_OUTPUTS,
    _init_acceptance_refusal_payload,
    _init_acceptance_success_payload,
)


def test_init_acceptance_success_payload_shape_is_stable() -> None:
    payload = _init_acceptance_success_payload()

    assert payload["command"] == "init-acceptance"
    assert payload["passed"] is True
    assert payload["status"] == "created"
    assert payload["created"] == list(_INIT_ACCEPTANCE_OUTPUTS)
    assert payload["next_actions"] == list(_INIT_ACCEPTANCE_NEXT_ACTIONS)


@given(existing_paths=st.lists(st.text(max_size=80), max_size=8))
def test_init_acceptance_refusal_payload_shape_is_stable(
    existing_paths: list[str],
) -> None:
    payload = _init_acceptance_refusal_payload(existing_paths)

    assert payload["command"] == "init-acceptance"
    assert payload["passed"] is False
    assert payload["status"] == "refused"
    assert payload["existing_paths"] == existing_paths
    assert payload["created"] == []
    assert payload["error"] == f"refusing to overwrite existing files: {', '.join(existing_paths)}"
    next_actions = payload["next_actions"]
    assert isinstance(next_actions, list)
    assert next_actions
