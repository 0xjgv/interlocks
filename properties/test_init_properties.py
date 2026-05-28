"""Generated-input checks for init JSON helpers."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from interlocks.scaffold import scaffold_status
from interlocks.tasks.init import (
    _INIT_NEXT_ACTIONS,
    _INIT_OUTPUTS,
    _init_refusal_payload,
    _init_success_payload,
)


@given(project_name=st.text(max_size=80))
def test_init_success_payload_shape_is_stable(project_name: str) -> None:
    files = [{"path": path, "action": "created"} for path in _INIT_OUTPUTS]

    payload = _init_success_payload(project_name, files)

    assert payload["command"] == "init"
    assert payload["passed"] is True
    assert payload["status"] == "created"
    assert payload["project_name"] == project_name
    assert payload["created"] == list(_INIT_OUTPUTS)
    assert payload["files"] == files
    assert payload["next_actions"] == list(_INIT_NEXT_ACTIONS)


@given(
    project_name=st.text(max_size=80),
    paths=st.lists(st.text(min_size=1, max_size=80), min_size=1, max_size=8, unique=True),
    actions=st.lists(st.sampled_from(("created", "kept")), min_size=1, max_size=8),
)
def test_init_success_payload_reports_created_subset(
    project_name: str,
    paths: list[str],
    actions: list[str],
) -> None:
    files = [
        {"path": path, "action": actions[index % len(actions)]} for index, path in enumerate(paths)
    ]

    payload = _init_success_payload(project_name, files)

    assert payload["status"] == scaffold_status(files)
    assert payload["project_name"] == project_name
    assert payload["created"] == [file["path"] for file in files if file["action"] == "created"]
    assert payload["files"] == files


@given(actions=st.lists(st.sampled_from(("created", "kept")), max_size=8))
def test_init_status_distinguishes_all_created(actions: list[str]) -> None:
    files = [
        {"path": f"tests/{index}.py", "action": action} for index, action in enumerate(actions)
    ]

    status = scaffold_status(files)

    assert status == ("created" if files and set(actions) == {"created"} else "scaffold-present")


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
