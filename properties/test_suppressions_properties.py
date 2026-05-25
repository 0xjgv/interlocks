"""Property tests for suppression comment parsing."""

from __future__ import annotations

import re
import string

from hypothesis import given
from hypothesis import strategies as st

from interlocks.reports.suppressions import _parse_line_for_suppressions

_NOQA_RULE = st.from_regex(r"[A-Z][A-Z0-9]{1,7}", fullmatch=True)
_TYPE_RULE = st.from_regex(r"[A-Za-z0-9_-]{1,16}", fullmatch=True)
_INVALID_NOQA_RULE = st.text(
    alphabet=string.ascii_lowercase + "_-",
    min_size=1,
    max_size=8,
).filter(lambda value: re.fullmatch(r"[A-Z][A-Z0-9]*(?:\s*,\s*[A-Z][A-Z0-9]*)*", value) is None)
_INVALID_BRACKET_RULE = st.sampled_from(("", "!", "arg type", "arg-type,", ",arg-type"))


def _noqa_fragment(rules: list[str]) -> str:
    return "# noqa" if not rules else f"# noqa: {', '.join(rules)}"


def _type_fragment(prefix: str, rules: list[str]) -> str:
    return f"# {prefix}: ignore" if not rules else f"# {prefix}: ignore[{', '.join(rules)}]"


@given(
    noqa_rules=st.lists(_NOQA_RULE, max_size=5),
    type_rules=st.lists(_TYPE_RULE, max_size=5),
    pyright_rules=st.lists(_TYPE_RULE, max_size=5),
)
def test_suppression_parser_round_trips_valid_constructed_comments(
    noqa_rules: list[str], type_rules: list[str], pyright_rules: list[str]
) -> None:
    line = (
        f"value = 1  {_noqa_fragment(noqa_rules)}  "
        f"{_type_fragment('type', type_rules)}  "
        f"{_type_fragment('pyright', pyright_rules)}"
    )

    assert _parse_line_for_suppressions(line) == [
        ("noqa", noqa_rules),
        ("type_ignore", type_rules),
        ("pyright_ignore", pyright_rules),
    ]


@given(rule=_INVALID_NOQA_RULE)
def test_suppression_parser_does_not_downgrade_invalid_noqa_to_broad(rule: str) -> None:
    matches = _parse_line_for_suppressions(f"value = 1  # noqa: {rule}")

    assert not any(kind == "noqa" for kind, _rules in matches)


@given(kind=st.sampled_from(("type", "pyright")), rule=_INVALID_BRACKET_RULE)
def test_suppression_parser_does_not_downgrade_invalid_brackets_to_broad(
    kind: str, rule: str
) -> None:
    matches = _parse_line_for_suppressions(f"value = 1  # {kind}: ignore[{rule}]")

    unexpected_kind = "type_ignore" if kind == "type" else "pyright_ignore"
    assert not any(match_kind == unexpected_kind for match_kind, _rules in matches)
