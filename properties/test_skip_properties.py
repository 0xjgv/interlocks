"""Property tests for global skip policy helpers."""

from __future__ import annotations

import sys
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import patch

import pytest
from hypothesis import given
from hypothesis import strategies as st

from interlocks.config import SKIP_LABELS
from interlocks.runner import Task
from interlocks.skip import (
    SkipPolicy,
    _cli_raw,
    _parse_csv,
    _skip_usage_payload,
    current_skip_policy,
    filter_tasks,
)

_KNOWN_LABELS = sorted(SKIP_LABELS)
_LABEL_LISTS = st.lists(st.sampled_from(_KNOWN_LABELS), max_size=len(_KNOWN_LABELS))
_LABEL_CHUNKS = st.lists(_LABEL_LISTS, min_size=1, max_size=5)
_UNKNOWN_LABELS = st.from_regex(r"[a-z][a-z0-9-]{0,20}", fullmatch=True).filter(
    lambda label: label not in SKIP_LABELS
)


@given(_LABEL_LISTS)
def test_parse_csv_normalizes_known_labels(labels: list[str]) -> None:
    raw = ",".join(f"  {label.upper()}  " for label in labels)

    assert _parse_csv(raw, source="property") == frozenset(labels)


@given(st.lists(st.text(alphabet=" \t", max_size=5), max_size=20))
def test_parse_csv_ignores_blank_tokens(parts: list[str]) -> None:
    raw = ",".join(parts)

    assert _parse_csv(raw, source="property") == frozenset()


@given(_LABEL_CHUNKS)
def test_current_skip_policy_merges_repeated_cli_skip_flags(chunks: list[list[str]]) -> None:
    args = [f"--skip={','.join(labels)}" for labels in chunks]
    expected = frozenset(label for labels in chunks for label in labels)

    current_skip_policy.cache_clear()
    try:
        with patch.object(sys, "argv", ["interlocks", "ci", *args]):
            policy = current_skip_policy()
    finally:
        current_skip_policy.cache_clear()

    assert policy.source == "cli"
    assert policy.labels == expected


@given(_LABEL_CHUNKS)
def test_cli_raw_merges_repeated_skip_values(chunks: list[list[str]]) -> None:
    args = [f"--skip={','.join(labels)}" for labels in chunks]
    original = sys.argv
    sys.argv = ["interlocks", "ci", *args]
    try:
        assert _cli_raw() == ",".join(",".join(labels) for labels in chunks)
    finally:
        sys.argv = original


@given(_UNKNOWN_LABELS)
def test_parse_csv_rejects_unknown_labels(label: str) -> None:
    with redirect_stderr(StringIO()), pytest.raises(SystemExit) as exc:
        _parse_csv(label, source="property")

    assert exc.value.code == 1


@given(
    command=st.one_of(st.none(), st.text(max_size=20)),
    message=st.text(min_size=1, max_size=80),
)
def test_skip_usage_payload_lists_known_label_domain(command: str | None, message: str) -> None:
    payload = _skip_usage_payload(message, command=command)

    assert payload["command"] == (command or "interlocks")
    assert payload["error"] == message
    assert payload["known_labels"] == sorted(SKIP_LABELS)
    assert "--skip=" in str(payload["usage"])


@given(
    labels=st.lists(st.sampled_from(_KNOWN_LABELS), unique=True),
    skipped=st.sets(st.sampled_from(_KNOWN_LABELS)),
)
def test_filter_tasks_removes_skipped_labels_in_order(
    labels: list[str],
    skipped: set[str],
) -> None:
    tasks = [Task(f"{label} task", ["noop"], label=label) for label in labels]
    policy = SkipPolicy(frozenset(skipped), "cli")

    with patch("interlocks.skip.warn_skipped") as warn_skipped:
        filtered = filter_tasks(tasks, policy)

    assert [task.label for task in filtered] == [label for label in labels if label not in skipped]
    assert [call.args[0] for call in warn_skipped.call_args_list] == [
        label for label in labels if label in skipped
    ]
