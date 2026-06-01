"""Property tests for shared CLI rendering helpers."""

from __future__ import annotations

import sys
from unittest.mock import patch

from hypothesis import given
from hypothesis import strategies as st

from interlocks import ui

_TEXT = st.text(alphabet=st.characters(blacklist_characters="\x1b"), max_size=80)
_ESC_BODY = st.text(
    alphabet=st.characters(blacklist_characters="\x1bm"),
    max_size=80,
)
_SGR = st.integers(min_value=0, max_value=107).map(lambda code: f"\x1b[{code}m")
_ARGV_TOKEN = st.text(
    alphabet=st.characters(blacklist_characters="\x00", blacklist_categories=("Cs",)),
    max_size=20,
).filter(lambda arg: arg != "--verbose")


@given(_TEXT)
def test_plain_len_matches_plain_text_length(text: str) -> None:
    assert ui._plain_len(text) == len(text)


@given(parts=st.lists(st.tuples(_TEXT, _SGR), max_size=20), tail=_TEXT)
def test_plain_len_ignores_complete_sgr_sequences(
    parts: list[tuple[str, str]],
    tail: str,
) -> None:
    rendered = "".join(f"{text}{escape}" for text, escape in parts) + tail
    expected = "".join(text for text, _escape in parts) + tail

    assert ui._plain_len(rendered) == len(expected)


@given(prefix=_TEXT, hidden=_ESC_BODY, suffix=_TEXT)
def test_plain_len_ignores_text_inside_escape_until_m(
    prefix: str,
    hidden: str,
    suffix: str,
) -> None:
    rendered = f"{prefix}\x1b{hidden}m{suffix}"

    assert ui._plain_len(rendered) == len(prefix) + len(suffix)


@given(
    detail=st.one_of(st.none(), _TEXT, st.integers()),
    state=st.text(max_size=20),
    force=st.booleans(),
)
def test_row_options_normalizes_detail_state_and_force(
    detail: object,
    state: str,
    force: bool,
) -> None:
    normalized_detail, normalized_state, normalized_force = ui._row_options({
        "detail": detail,
        "state": state,
        "force": force,
    })

    assert normalized_detail == (detail if isinstance(detail, str) else None)
    assert normalized_state == (state if state in ui._STATE_COLORS else "ok")
    assert normalized_force is force


@given(
    is_json=st.booleans(),
    verbose=st.booleans(),
    force=st.booleans(),
    state=st.sampled_from(("ok", "warn", "fail")),
)
def test_suppress_row_matches_json_verbose_force_contract(
    is_json: bool,
    verbose: bool,
    force: bool,
    state: ui.State,
) -> None:
    with (
        patch.object(ui, "is_json", return_value=is_json),
        patch.object(ui, "is_verbose", return_value=verbose),
    ):
        suppressed = ui._suppress_row(force=force, state=state)

    assert suppressed is (is_json or (not force and not verbose and state != "fail"))


@given(
    status=_TEXT, detail=st.one_of(st.none(), _TEXT), state=st.sampled_from(("ok", "warn", "fail"))
)
def test_row_suffix_joins_detail_and_status_without_color(
    status: str,
    detail: str | None,
    state: ui.State,
) -> None:
    with patch.object(ui, "use_color", return_value=False):
        suffix = ui._row_suffix(status, detail, state)

    assert suffix == (f"{detail} {status}" if detail else status)


@given(code=_TEXT, text=_TEXT, use_color=st.booleans())
def test_color_wrapper_honors_color_mode(code: str, text: str, use_color: bool) -> None:
    with patch.object(ui, "use_color", return_value=use_color):
        rendered = ui._c(code, text)

    assert rendered == (f"{code}{text}{ui._RESET}" if use_color else text)


@given(action=_TEXT, indent=_TEXT)
def test_next_action_line_lowercases_first_character(action: str, indent: str) -> None:
    assert ui.next_action_line(action, indent=indent) == (
        f"{indent}next: {action[:1].lower()}{action[1:]}"
    )


@given(prefix=st.lists(_ARGV_TOKEN, max_size=5), suffix=st.lists(_ARGV_TOKEN, max_size=5))
def test_is_verbose_matches_exact_argv_membership(prefix: list[str], suffix: list[str]) -> None:
    with patch.object(sys, "argv", [*prefix, "--verbose", *suffix]):
        assert ui.is_verbose() is True

    with patch.object(sys, "argv", [*prefix, *suffix]):
        assert ui.is_verbose() is False
