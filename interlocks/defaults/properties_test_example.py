"""Example property test.

Delete or replace this once your project has domain-specific invariants.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st


@given(st.lists(st.integers()))
def test_sorted_preserves_length(values: list[int]) -> None:
    assert len(sorted(values)) == len(values)
