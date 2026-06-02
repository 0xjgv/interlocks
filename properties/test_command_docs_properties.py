"""Property tests for command metadata helpers."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from interlocks.command_docs import (
    ALIASES,
    COMMAND_DOCS_BY_NAME,
    GLOBAL_FLAGS,
    _flag_sets_for_task,
    _unknown_flag,
    alias_suffix,
    aliases_for,
    command_doc_payload,
    command_index_payload,
    command_mutation_summary,
    command_usage,
    unknown_task_flags,
)

_DOC_FLAGS = tuple(
    (task_name, spec.name, spec.kind)
    for task_name, doc in sorted(COMMAND_DOCS_BY_NAME.items())
    for spec in doc.flags
)
_TASK_NAMES = tuple(sorted(COMMAND_DOCS_BY_NAME))
_NON_HELP_TASK_NAMES = tuple(name for name in _TASK_NAMES if name != "help")
_CANONICAL_ALIASED_NAMES = tuple(sorted(set(ALIASES.values())))
_ARG_TOKENS = st.one_of(
    st.text(max_size=20),
    st.from_regex(r"--[A-Za-z][A-Za-z0-9-]*(?:=.*)?", fullmatch=True),
    st.from_regex(r"-[A-Za-z](?:=.*)?", fullmatch=True),
)


@given(st.text().filter(lambda value: not value.startswith("-")))
def test_non_flag_tokens_are_never_unknown_flags(arg: str) -> None:
    assert _unknown_flag(arg, frozenset(), frozenset(), ()) is False


@given(st.sampled_from(sorted(GLOBAL_FLAGS)))
def test_global_flags_are_never_unknown(flag: str) -> None:
    assert _unknown_flag(flag, frozenset(), frozenset(), ()) is False


@given(st.text())
def test_skip_flag_is_global_even_with_value(value: str) -> None:
    assert _unknown_flag("--skip", frozenset(), frozenset(), ()) is False
    assert _unknown_flag(f"--skip={value}", frozenset(), frozenset(), ()) is False


@given(
    name=st.from_regex(r"--[a-z]+(?:-[a-z]+)*", fullmatch=True),
    value=st.text(),
)
def test_declared_boolean_flag_accepts_only_bare_form(name: str, value: str) -> None:
    declared = frozenset({name})

    assert _unknown_flag(name, declared, frozenset(), ()) is False
    assert _unknown_flag(f"{name}={value}", declared, frozenset(), ()) is True


@given(
    name=st.from_regex(r"--[a-z]+(?:-[a-z]+)*", fullmatch=True),
    value=st.text(),
)
def test_declared_optional_flag_accepts_bare_and_value_forms(name: str, value: str) -> None:
    declared = frozenset({name})

    assert _unknown_flag(name, frozenset(), declared, ()) is False
    assert _unknown_flag(f"{name}={value}", frozenset(), declared, ()) is False


@given(
    name=st.from_regex(r"--[a-z]+(?:-[a-z]+)*", fullmatch=True),
    value=st.text(),
)
def test_declared_value_flag_accepts_prefixed_value(name: str, value: str) -> None:
    assert _unknown_flag(f"{name}={value}", frozenset(), frozenset(), (f"{name}=",)) is False


@given(st.sampled_from(_DOC_FLAGS), st.text())
def test_documented_task_flags_are_accepted(
    task_and_flag: tuple[str, str, str],
    value: str,
) -> None:
    task_name, flag, kind = task_and_flag
    if flag.endswith("="):
        accepted = [f"{flag}{value}"]
    elif kind == "optional":
        accepted = [flag, f"{flag}={value}"]
    else:
        accepted = [flag]

    assert unknown_task_flags(task_name, accepted) == []


@given(task_name=st.sampled_from(_TASK_NAMES))
def test_flag_sets_for_task_partition_declared_flag_kinds(task_name: str) -> None:
    doc = COMMAND_DOCS_BY_NAME[task_name]
    boolean_names, optional_names, value_prefixes = _flag_sets_for_task(task_name)

    assert boolean_names == frozenset(
        spec.name for spec in doc.flags if spec.kind == "boolean" and not spec.name.endswith("=")
    )
    assert optional_names == frozenset(spec.name for spec in doc.flags if spec.kind == "optional")
    assert value_prefixes == tuple(spec.name for spec in doc.flags if spec.name.endswith("="))


@given(task_name=st.sampled_from(_TASK_NAMES))
def test_flag_sets_for_task_are_disjoint(task_name: str) -> None:
    boolean_names, optional_names, value_prefixes = _flag_sets_for_task(task_name)

    assert boolean_names.isdisjoint(optional_names)
    assert boolean_names.isdisjoint(value_prefixes)
    assert optional_names.isdisjoint(value_prefixes)


@given(task_name=st.text().filter(lambda name: name not in COMMAND_DOCS_BY_NAME))
def test_flag_sets_for_unknown_task_are_empty(task_name: str) -> None:
    assert _flag_sets_for_task(task_name) == (frozenset(), frozenset(), ())


@given(task_name=st.sampled_from(_TASK_NAMES))
def test_command_usage_is_declared_tail_or_command_name(task_name: str) -> None:
    doc = COMMAND_DOCS_BY_NAME[task_name]
    usage = command_usage(doc)

    assert usage == (doc.usage or doc.name)
    assert usage.startswith(doc.name)
    assert "\n" not in usage


@given(task_name=st.sampled_from(_TASK_NAMES))
def test_command_mutation_summary_uses_note_or_boolean(task_name: str) -> None:
    doc = COMMAND_DOCS_BY_NAME[task_name]
    summary = command_mutation_summary(doc)

    assert summary == (doc.mutates_note or ("yes" if doc.mutates else "no"))
    assert summary
    assert "\n" not in summary


@given(task_name=st.sampled_from(_TASK_NAMES))
def test_command_index_payload_projects_compact_doc_fields(task_name: str) -> None:
    doc = COMMAND_DOCS_BY_NAME[task_name]
    payload = command_index_payload(doc)

    assert payload == {
        "name": doc.name,
        "summary": doc.summary,
        "aliases": aliases_for(doc.name),
    }


@given(task_name=st.sampled_from(_TASK_NAMES))
def test_command_doc_payload_projects_full_doc_contract(task_name: str) -> None:
    doc = COMMAND_DOCS_BY_NAME[task_name]
    payload = command_doc_payload(doc)

    assert payload["command"] == doc.name
    assert payload["usage"] == f"usage: interlocks {command_usage(doc)}"
    assert payload["summary"] == doc.summary
    assert payload["when_to_use"] == doc.when_to_use
    assert payload["mutates"] is doc.mutates
    assert payload["mutates_note"] == command_mutation_summary(doc)
    assert payload["outputs"] == list(doc.outputs)
    assert payload["aliases"] == aliases_for(doc.name)
    flags = payload["flags"]
    exit_codes = payload["exit_codes"]
    assert isinstance(flags, list)
    assert isinstance(exit_codes, list)
    assert len(flags) == len(doc.flags)
    assert len(exit_codes) == len(doc.exit_codes)


@given(task_name=st.sampled_from(_NON_HELP_TASK_NAMES), value=st.text())
def test_advanced_flag_is_help_only(task_name: str, value: str) -> None:
    assert unknown_task_flags(task_name, ["--advanced"]) == ["--advanced"]
    token = f"--advanced={value}"
    assert unknown_task_flags(task_name, [token]) == [token]


@given(task_name=st.sampled_from(_TASK_NAMES), raw_args=st.lists(_ARG_TOKENS, max_size=30))
def test_unknown_task_flags_preserves_bad_flag_order(
    task_name: str,
    raw_args: list[str],
) -> None:
    doc = COMMAND_DOCS_BY_NAME[task_name]
    value_prefixes = tuple(spec.name for spec in doc.flags if spec.name.endswith("="))
    optional_names = frozenset(spec.name for spec in doc.flags if spec.kind == "optional")
    boolean_names = frozenset(
        spec.name for spec in doc.flags if spec.kind == "boolean" and not spec.name.endswith("=")
    )

    assert unknown_task_flags(task_name, raw_args) == [
        arg
        for arg in raw_args
        if _unknown_flag(arg, boolean_names, optional_names, value_prefixes)
    ]


@given(st.sampled_from(_CANONICAL_ALIASED_NAMES))
def test_alias_suffix_lists_sorted_aliases_for_canonical_name(name: str) -> None:
    aliases = sorted(alias for alias, canonical in ALIASES.items() if canonical == name)
    label = "alias" if len(aliases) == 1 else "aliases"

    assert alias_suffix(name) == f" ({label}: {', '.join(aliases)})"


@given(st.text().filter(lambda name: name not in set(ALIASES.values())))
def test_alias_suffix_is_empty_without_alias(name: str) -> None:
    assert not alias_suffix(name)


@given(
    st.sampled_from(
        tuple(name for name in _CANONICAL_ALIASED_NAMES if len(aliases_for(name)) == 1)
    )
)
def test_alias_suffix_uses_singular_label_for_one_alias(name: str) -> None:
    [alias] = aliases_for(name)

    assert alias_suffix(name) == f" (alias: {alias})"
