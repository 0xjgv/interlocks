"""Property tests for clean-stage artifact classification."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given
from hypothesis import strategies as st

from interlocks.runner import record_result, reset_results
from interlocks.stages.clean import (
    _artifact_label,
    _clean_payload,
    _is_artifact_dir,
    _iter_recursive_artifacts,
    _removed_payload_fields,
)


@given(name=st.text(max_size=80))
def test_is_artifact_dir_matches_pycache_or_egg_info_names(name: str) -> None:
    assert _is_artifact_dir(name) is (name == "__pycache__" or name.endswith(".egg-info"))


@given(prefix=st.text(max_size=20), suffix=st.text(max_size=20))
def test_is_artifact_dir_does_not_match_partial_pycache_names(prefix: str, suffix: str) -> None:
    name = f"{prefix}__pycache__{suffix}"

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


@given(paths=st.lists(st.text(min_size=1, max_size=20), max_size=80))
def test_removed_payload_fields_are_snapshot_not_live_list(paths: list[str]) -> None:
    payload = _removed_payload_fields(paths)
    original_removed = list(payload["removed"])

    paths.append("late-artifact")

    assert payload["removed_count"] == len(paths) - 1
    assert payload["removed"] == original_removed


@given(
    has_pycache=st.booleans(),
    has_egg_info=st.booleans(),
    has_pyc=st.booleans(),
    has_pyo=st.booleans(),
    has_txt=st.booleans(),
    has_git_pyc=st.booleans(),
)
def test_iter_recursive_artifacts_finds_artifacts_but_skips_git(
    has_pycache: bool,
    has_egg_info: bool,
    has_pyc: bool,
    has_pyo: bool,
    has_txt: bool,
    has_git_pyc: bool,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        pkg = root / "pkg"
        pkg.mkdir()
        expected: set[str] = set()
        if has_pycache:
            (pkg / "__pycache__").mkdir()
            (pkg / "__pycache__" / "inside.pyc").write_text("", encoding="utf-8")
            expected.add("pkg/__pycache__")
        if has_egg_info:
            (pkg / "pkg.egg-info").mkdir()
            expected.add("pkg/pkg.egg-info")
        if has_pyc:
            (pkg / "module.pyc").write_text("", encoding="utf-8")
            expected.add("pkg/module.pyc")
        if has_pyo:
            (pkg / "module.pyo").write_text("", encoding="utf-8")
            expected.add("pkg/module.pyo")
        if has_txt:
            (pkg / "module.txt").write_text("", encoding="utf-8")
        if has_git_pyc:
            git = root / ".git"
            git.mkdir()
            (git / "ignored.pyc").write_text("", encoding="utf-8")

        artifacts = {_artifact_label(root, path) for path in _iter_recursive_artifacts(root)}

    assert artifacts == expected


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


@given(
    removed=st.lists(st.text(min_size=1, max_size=20), min_size=51, max_size=80),
    elapsed=st.floats(min_value=0, max_value=1000, allow_nan=False, allow_infinity=False),
)
def test_clean_payload_reports_omitted_removed_count(
    removed: list[str],
    elapsed: float,
) -> None:
    reset_results()

    payload = _clean_payload(removed, elapsed)

    assert payload["omitted_removed"] == len(removed) - 50


@given(elapsed=st.floats(min_value=0, max_value=1000, allow_nan=False, allow_infinity=False))
def test_clean_payload_reports_failed_status_from_recorded_gate(elapsed: float) -> None:
    reset_results()
    try:
        record_result("generated", status="fail", elapsed=elapsed, detail=None)

        payload = _clean_payload([], elapsed)
    finally:
        reset_results()

    assert payload["passed"] is False
    assert payload["status"] == "failed"


@given(relpath=st.from_regex(r"\.?/?[A-Za-z0-9_.-]{1,20}", fullmatch=True))
def test_artifact_label_strips_leading_dot_slash(relpath: str) -> None:
    label = _artifact_label(Path(), Path(relpath))

    assert not label.startswith("./")
