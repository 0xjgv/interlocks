"""Property tests for clean-stage artifact classification."""

from __future__ import annotations

from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from interlocks.runner import reset_results
from interlocks.stages.clean import (
    _artifact_label,
    _clean_payload,
    _is_artifact_dir,
    _removed_payload_fields,
)


@given(name=st.text(max_size=80))
def test_is_artifact_dir_matches_pycache_or_egg_info_names(name: str) -> None:
    assert _is_artifact_dir(name) is (name == "__pycache__" or name.endswith(".egg-info"))


@given(paths=st.lists(st.text(min_size=1, max_size=20), max_size=80))
def test_removed_payload_fields_caps_removed_sample(paths: list[str]) -> None:
    payload = _removed_payload_fields(paths)

    assert payload["removed_count"] == len(paths)
    assert payload["removed"] == paths[:50]
    omitted = len(paths) - 50
    if omitted > 0:
        assert payload["omitted_removed"] == omitted
    else:
        assert "omitted_removed" not in payload


@given(
    removed=st.lists(st.text(min_size=1, max_size=20), max_size=80),
    elapsed=st.floats(min_value=0, max_value=1000, allow_nan=False, allow_infinity=False),
)
def test_clean_payload_includes_removed_sample_and_empty_gate_state(
    removed: list[str],
    elapsed: float,
) -> None:
    reset_results()

    payload = _clean_payload(removed, elapsed)

    assert payload["command"] == "clean"
    assert payload["passed"] is True
    assert payload["elapsed_seconds"] == round(elapsed, 3)
    assert payload["gates"] == []
    assert payload["skipped"] == []
    assert payload["status"] == "cleaned"
    assert payload["removed_count"] == len(removed)
    assert payload["removed"] == removed[:50]


@given(relpath=st.from_regex(r"\.?/?[A-Za-z0-9_.-]{1,20}", fullmatch=True))
def test_artifact_label_strips_leading_dot_slash(relpath: str) -> None:
    label = _artifact_label(Path(), Path(relpath))

    assert not label.startswith("./")
