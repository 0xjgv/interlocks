"""Property tests for lintfix apply/verify helpers."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from interlocks.lintfix.verify import _candidate_files

_SEGMENT = st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,10}", fullmatch=True)
_FILE = st.lists(_SEGMENT, min_size=1, max_size=4).map(lambda parts: "/".join(parts) + ".py")
_RULE = st.from_regex(r"[A-Z][A-Z0-9]{1,6}", fullmatch=True)
_CANDIDATE = st.tuples(
    st.sampled_from(("lint", "format")),
    _RULE,
    st.lists(_FILE, max_size=5, unique=True).map(tuple),
)


@given(candidates=st.lists(_CANDIDATE, max_size=12))
def test_candidate_files_returns_unique_union(
    candidates: list[tuple[str, str, tuple[str, ...]]],
) -> None:
    files = _candidate_files(candidates)
    expected = {file for _kind, _rule, candidate_files in candidates for file in candidate_files}

    assert set(files) == expected
    assert len(files) == len(expected)


@given(rule=_RULE)
def test_candidate_files_ignores_candidates_without_files(rule: str) -> None:
    assert _candidate_files((("lint", rule, ()), ("format", rule, ()))) == ()


@given(file=_FILE, rules=st.lists(_RULE, min_size=1, max_size=8))
def test_candidate_files_deduplicates_one_file_across_rules(
    file: str,
    rules: list[str],
) -> None:
    candidates = tuple(("lint", rule, (file,)) for rule in rules)

    assert _candidate_files(candidates) == (file,)
