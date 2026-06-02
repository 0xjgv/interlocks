"""Property tests for explain-command lookup helpers."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from interlocks.command_docs import ALIASES, COMMAND_DOCS_BY_NAME
from interlocks.tasks import explain

_KNOWN_REQUEST = st.sampled_from(tuple(COMMAND_DOCS_BY_NAME) + tuple(ALIASES))
_KNOWN_POSITIONAL = st.sampled_from(
    tuple((name.split(), ALIASES.get(name, name)) for name in COMMAND_DOCS_BY_NAME)
    + tuple((alias.split(), target) for alias, target in ALIASES.items())
)
_UNKNOWN_REQUEST = st.text(min_size=1, max_size=50).filter(
    lambda request: request not in COMMAND_DOCS_BY_NAME and request not in ALIASES
)
_DOC_NAME = st.sampled_from(tuple(sorted(COMMAND_DOCS_BY_NAME)))


@given(requested=_KNOWN_REQUEST)
def test_resolve_doc_returns_registered_command_or_alias_target(requested: str) -> None:
    resolved = ALIASES.get(requested, requested)

    assert explain._resolve_doc(requested) is COMMAND_DOCS_BY_NAME[resolved]


@given(requested=_UNKNOWN_REQUEST)
def test_resolve_doc_rejects_unknown_commands(requested: str) -> None:
    with pytest.raises(SystemExit) as exc_info:
        explain._resolve_doc(requested)

    assert exc_info.value.code == 1


@given(requested=_KNOWN_REQUEST, want_all=st.booleans())
def test_explain_payload_for_single_command_uses_resolved_doc(
    requested: str,
    want_all: bool,
) -> None:
    resolved = ALIASES.get(requested, requested)

    payload = explain._explain_payload(want_all=want_all, positional=[requested])

    assert payload["command"] == resolved
    assert str(payload["usage"]).startswith(f"usage: interlocks {resolved}")
    assert "when_to_use" in payload


@given(command_pair=_KNOWN_POSITIONAL)
def test_explain_payload_joins_nested_command_tokens(
    command_pair: tuple[list[str], str],
) -> None:
    positional, resolved = command_pair

    payload = explain._explain_payload(want_all=False, positional=positional)

    assert payload["command"] == resolved


@given(want_all=st.booleans())
def test_explain_payload_without_positionals_uses_index_or_all_mode(want_all: bool) -> None:
    payload = explain._explain_payload(want_all=want_all, positional=[])

    assert payload["command"] == "explain"
    assert payload["mode"] == ("all" if want_all else "index")
    assert payload["groups"] == explain._explain_groups_payload(full=want_all)


@given(full=st.booleans())
def test_explain_groups_payload_lists_every_registered_command_once(full: bool) -> None:
    payload = explain._explain_groups_payload(full=full)
    commands: list[dict[str, object]] = []
    for group in payload:
        group_commands = group["commands"]
        assert isinstance(group_commands, list)
        for command in group_commands:
            assert isinstance(command, dict)
            commands.append(command)
    key = "command" if full else "name"

    assert {command[key] for command in commands} == set(COMMAND_DOCS_BY_NAME)
    assert len(commands) == len(COMMAND_DOCS_BY_NAME)
    assert all(("when_to_use" in command) is full for command in commands)


@given(full=st.booleans())
def test_explain_groups_payload_has_no_empty_groups(full: bool) -> None:
    payload = explain._explain_groups_payload(full=full)

    assert payload
    assert all(group["commands"] for group in payload)


@given(task_name=_DOC_NAME, full=st.booleans())
def test_explain_command_payload_switches_between_index_and_full_doc(
    task_name: str,
    full: bool,
) -> None:
    payload = explain._explain_command_payload(
        task_name,
        COMMAND_DOCS_BY_NAME[task_name],
        full=full,
    )

    assert payload["command" if full else "name"] == task_name
    assert ("when_to_use" in payload) is full


@given(task_name=_DOC_NAME)
def test_explain_command_payload_index_shape_uses_summary_without_full_doc(
    task_name: str,
) -> None:
    payload = explain._explain_command_payload(
        task_name,
        COMMAND_DOCS_BY_NAME[task_name],
        full=False,
    )

    assert payload["name"] == task_name
    assert "summary" in payload
    assert "usage" not in payload


@given(name=st.text(max_size=50), full=st.booleans())
def test_explain_command_payload_degrades_when_doc_is_missing(name: str, full: bool) -> None:
    payload = explain._explain_command_payload(name, None, full=full)

    assert payload == {
        "name": name,
        "summary": "(no explanation registered)",
        "aliases": [],
    }
