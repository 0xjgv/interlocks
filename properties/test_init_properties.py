"""Generated-input checks for init JSON helpers."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from interlocks.tasks.init import (
    _INIT_NEXT_ACTIONS,
    _INIT_OUTPUTS,
    _init_refusal_payload,
    _init_success_payload,
)


@given(project_name=st.text(max_size=80))
def test_init_success_payload_shape_is_stable(project_name: str) -> None:
    payload = _init_success_payload(project_name)

    assert payload["command"] == "init"
    assert payload["passed"] is True
    assert payload["status"] == "created"
    assert payload["project_name"] == project_name
    assert payload["created"] == list(_INIT_OUTPUTS)
    assert payload["next_actions"] == list(_INIT_NEXT_ACTIONS)


@given(existing_path=st.text(max_size=120))
def test_init_refusal_payload_shape_is_stable(existing_path: str) -> None:
    payload = _init_refusal_payload(existing_path)

    assert payload["command"] == "init"
    assert payload["passed"] is False
    assert payload["status"] == "refused"
    assert payload["existing_path"] == existing_path
    assert payload["created"] == []
    assert payload["error"] == f"refusing to overwrite existing {existing_path}"
    next_actions = payload["next_actions"]
    assert isinstance(next_actions, list)
    assert next_actions
