"""Property tests for targeted pyproject.toml rewrites."""

from __future__ import annotations

import json

from hypothesis import given
from hypothesis import strategies as st

from interlocks.pyproject_edit import (
    _ArrayValueScan,
    _format_array,
    _mutmut_slice,
    _rewrite,
    _value_is_multiline,
)

_PATHS = st.lists(st.text(max_size=20), max_size=5)
_BODY_LINES = st.lists(
    st.text(
        alphabet=st.characters(blacklist_characters="\r\n"),
        max_size=30,
    ).filter(lambda line: not line.startswith("[")),
    max_size=8,
)


@given(_PATHS)
def test_format_array_round_trips_as_json_array(paths: list[str]) -> None:
    assert json.loads(_format_array(paths)) == paths


@given(_PATHS)
def test_formatted_arrays_are_single_line_values(paths: list[str]) -> None:
    assert _value_is_multiline(_format_array(paths)) is False


@given(st.text(alphabet=st.characters(blacklist_characters="\r\n"), max_size=80))
def test_array_scan_consume_matches_single_line_array_detection(tail: str) -> None:
    value = f"[{tail}"
    scan = _ArrayValueScan()

    closed = any(scan.consume(ch) for ch in value)

    assert closed is not _value_is_multiline(value)


@given(st.characters(blacklist_characters="'\\"))
def test_array_scan_quoted_single_quote_stays_open(ch: str) -> None:
    scan = _ArrayValueScan(quote="'")

    scan._consume_quoted(ch)

    assert scan.quote == "'"


@given(st.characters(blacklist_characters="[]#'\""))
def test_array_scan_unquoted_plain_character_does_not_close(ch: str) -> None:
    scan = _ArrayValueScan()

    assert scan._consume_unquoted(ch) is False
    assert scan.depth == 0


@given(before=_BODY_LINES, body=_BODY_LINES, after=_BODY_LINES)
def test_mutmut_slice_returns_only_tool_mutmut_body(
    before: list[str],
    body: list[str],
    after: list[str],
) -> None:
    prefix = "\n".join(["[project]", *before, ""])
    mutmut_body = "\n".join(["", *body, ""])
    suffix = "\n".join(["[tool.ruff]", *after, ""])
    text = f"{prefix}[tool.mutmut]{mutmut_body}{suffix}"

    slice_range = _mutmut_slice(text)

    assert slice_range is not None
    start, end = slice_range
    assert text[start:end] == mutmut_body


@given(table=st.sampled_from(["tool.ruff", "tool.mutmutation", "tool.mutmut.extra"]))
def test_mutmut_slice_ignores_other_tables(table: str) -> None:
    text = f"[{table}]\npaths_to_mutate = []\n"

    assert _mutmut_slice(text) is None


@given(existing=_PATHS, replacement=_PATHS)
def test_rewrite_replaces_generated_single_line_arrays(
    existing: list[str],
    replacement: list[str],
) -> None:
    source = f"""\
[tool.mutmut]
paths_to_mutate = {_format_array(existing)}
tests_dir = ["tests/"]
"""

    rewritten = _rewrite(source, replacement)

    assert f"paths_to_mutate = {_format_array(replacement)}" in rewritten
    assert 'tests_dir = ["tests/"]' in rewritten
