"""Property tests for setup-state inspection helpers."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from interlocks.setup_state import text_references_check_stage


@given(text=st.text(max_size=200))
def test_text_references_check_stage_matches_documented_needles(text: str) -> None:
    lowered = text.lower()
    expected = "interlocks check" in lowered or "il check" in lowered

    assert text_references_check_stage(text) is expected


@given(prefix=st.text(max_size=40), suffix=st.text(max_size=40), shorthand=st.booleans())
def test_text_references_check_stage_is_case_insensitive(
    prefix: str,
    suffix: str,
    shorthand: bool,
) -> None:
    command = "IL CHECK" if shorthand else "INTERLOCKS CHECK"

    assert text_references_check_stage(f"{prefix}{command}{suffix}") is True
