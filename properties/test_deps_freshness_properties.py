"""Property tests for dependency freshness output parsing."""

from __future__ import annotations

import json
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from interlocks.tasks.deps_freshness import (
    _freshness_payload,
    _FreshnessLookup,
    _outdated_packages,
)

_JSON_SCALARS = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-1_000_000, max_value=1_000_000),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=30),
)
_JSON_VALUES = st.recursive(
    _JSON_SCALARS,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.text(max_size=20), children, max_size=4),
    ),
    max_leaves=20,
)
_JSON_OBJECTS = st.dictionaries(st.text(max_size=20), _JSON_VALUES, max_size=5)


@given(st.text(max_size=2_000))
def test_outdated_packages_never_raises(raw: str) -> None:
    assert all(isinstance(package, dict) for package in _outdated_packages(raw))


@given(st.lists(st.one_of(_JSON_OBJECTS, _JSON_VALUES), max_size=20))
def test_outdated_packages_keeps_only_json_objects(values: list[Any]) -> None:
    output = json.dumps(values)
    expected = [value for value in values if isinstance(value, dict)]

    assert _outdated_packages(output) == expected


@given(_JSON_VALUES.filter(lambda value: not isinstance(value, list)))
def test_outdated_packages_rejects_non_array_json(value: Any) -> None:
    assert _outdated_packages(json.dumps(value)) == []


@given(
    command=st.text(max_size=80),
    returncode=st.integers(min_value=0, max_value=255),
    values=st.lists(st.one_of(_JSON_OBJECTS, _JSON_VALUES), max_size=20),
    used_fallback=st.booleans(),
    elapsed=st.floats(allow_nan=False, allow_infinity=False, min_value=0, max_value=10_000),
)
def test_freshness_payload_matches_lookup_result(
    command: str,
    returncode: int,
    values: list[Any],
    used_fallback: bool,
    elapsed: float,
) -> None:
    stdout = json.dumps(values)
    lookup = _FreshnessLookup(
        command=command,
        returncode=returncode,
        stdout=stdout,
        stderr="",
        used_fallback=used_fallback,
        elapsed=elapsed,
    )

    payload = _freshness_payload(lookup)

    assert payload["command"] == "deps-freshness"
    assert payload["lookup_command"] == command
    assert payload["fallback_used"] is used_fallback
    assert payload["elapsed_seconds"] == round(elapsed, 3)
    if returncode != 0:
        assert payload["passed"] is False
        assert payload["status"] == "failed"
        assert payload["returncode"] == returncode
        assert "outdated" not in payload
        return

    expected = [value for value in values if isinstance(value, dict)]
    assert payload["outdated_count"] == len(expected)
    assert payload["outdated"] == expected
    assert payload["passed"] is (not expected)
    assert payload["status"] == ("failed" if expected else "ok")
    assert ("next_actions" in payload) is bool(expected)
