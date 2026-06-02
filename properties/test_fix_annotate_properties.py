"""Property tests for lintfix GitHub annotation formatting."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from interlocks.tasks.fix_annotate import (
    AnnotationResult,
    _annotations_for,
    _collect_annotation_counts,
    _fix_annotate_payload,
    _flatten_optimize,
    _format_message,
    _iter_candidates,
)

_CLASSIFICATIONS = st.sampled_from(["auto", "escrow", "advisory", "skip", "needs_data"])
_JSONISH = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-100, max_value=100),
    st.text(max_size=40),
    st.lists(st.text(max_size=20), max_size=5),
    st.dictionaries(st.text(max_size=20), st.text(max_size=20), max_size=5),
)


@st.composite
def annotation_candidates(draw: Any) -> dict[str, object]:
    files = draw(st.lists(st.text(max_size=30), max_size=5))
    return {
        "rule": draw(st.text(min_size=1, max_size=30)),
        "classification": draw(_CLASSIFICATIONS),
        "files": files,
        "files_touched": draw(st.integers(min_value=0, max_value=1_000)),
        "changed_lines_total": draw(st.integers(min_value=0, max_value=1_000_000)),
        "changed_lines_outside_diff": draw(st.integers(min_value=0, max_value=1_000_000)),
        "risk": draw(st.integers(min_value=0, max_value=1_000_000)),
        "patch_path": draw(st.one_of(st.none(), st.text(max_size=50))),
    }


@given(annotation_candidates())
def test_annotations_are_single_line_workflow_commands(candidate: dict[str, object]) -> None:
    annotations = list(_annotations_for(candidate))

    for annotation in annotations:
        assert annotation.line.startswith(f"::{annotation.severity}")
        assert "\n" not in annotation.line
        assert "\r" not in annotation.line


@given(annotation_candidates())
def test_annotation_count_matches_classification_and_file_count(
    candidate: dict[str, object],
) -> None:
    annotations = list(_annotations_for(candidate))
    classification = candidate["classification"]
    files = candidate["files"]

    if classification not in {"auto", "escrow", "advisory"}:
        assert annotations == []
    elif files:
        assert len(annotations) == len(files)
    else:
        assert len(annotations) == 1


@given(
    st.dictionaries(
        st.text(max_size=20),
        st.one_of(st.integers(), st.text(max_size=40)),
        max_size=20,
    )
)
def test_annotations_ignore_malformed_candidates_without_traceback(
    candidate: dict[str, object],
) -> None:
    annotations = list(_annotations_for(candidate))

    for annotation in annotations:
        assert "\n" not in annotation.line
        assert "\r" not in annotation.line


@given(
    st.dictionaries(
        st.text(max_size=20),
        st.one_of(st.integers(), st.text(max_size=40)),
        max_size=20,
    )
)
def test_format_message_accepts_partial_candidate_shapes(candidate: dict[str, object]) -> None:
    message = _format_message(candidate)

    assert isinstance(message, str)
    assert "files" in message


@given(
    files=st.lists(st.text(max_size=20), max_size=5),
    files_touched=st.integers(min_value=0, max_value=100),
)
def test_format_message_preserves_explicit_file_count(
    files: list[str],
    files_touched: int,
) -> None:
    message = _format_message({
        "rule": "I001",
        "classification": "auto",
        "files": files,
        "files_touched": files_touched,
        "changed_lines_total": 0,
        "changed_lines_outside_diff": 0,
        "risk": 0,
    })

    assert f": {files_touched} files," in message


_SINGLE_LINE = st.text(
    alphabet=st.characters(blacklist_characters="\r\n"),
    min_size=1,
    max_size=40,
)


@given(rule=_SINGLE_LINE, patch_path=_SINGLE_LINE)
def test_format_message_adds_review_suffix_only_for_escrow_patch(
    rule: str,
    patch_path: str,
) -> None:
    escrow = _format_message({
        "rule": rule,
        "classification": "escrow",
        "files": [],
        "patch_path": patch_path,
    })
    advisory = _format_message({
        "rule": rule,
        "classification": "advisory",
        "files": [],
        "patch_path": patch_path,
    })

    assert escrow.endswith(f"Patch staged at {patch_path}; review before applying.")
    assert "Patch staged" not in advisory


@given(rule=_SINGLE_LINE)
def test_format_message_auto_classification_names_apply_command(rule: str) -> None:
    message = _format_message({
        "rule": rule,
        "classification": "auto",
        "files": [],
    })

    assert message.endswith(f"Apply with `interlocks fix-rule --rule={rule} --apply`.")


@given(payload=st.dictionaries(st.text(max_size=20), _JSONISH, max_size=10))
def test_iter_candidates_ignores_malformed_plan_payloads(
    payload: dict[str, object],
) -> None:
    candidates = list(_iter_candidates(payload, "plan"))

    assert all(isinstance(candidate, dict) for candidate in candidates)
    for candidate in candidates:
        list(_annotations_for(candidate))


@given(payload=st.dictionaries(st.text(max_size=20), _JSONISH, max_size=10))
def test_iter_candidates_ignores_malformed_optimize_payloads(
    payload: dict[str, object],
) -> None:
    candidates = list(_iter_candidates(payload, "optimize"))

    assert all(isinstance(candidate, dict) for candidate in candidates)
    assert all(isinstance(candidate.get("classification"), str) for candidate in candidates)
    for candidate in candidates:
        list(_annotations_for(candidate))


@given(
    policy_mode=st.text(min_size=1, max_size=20),
    files=st.one_of(st.lists(st.text(max_size=20), max_size=5), st.text(max_size=20)),
    cost=st.one_of(
        st.dictionaries(
            st.sampled_from(["files", "changed_lines", "outside_diff", "risk"]),
            st.integers(min_value=0, max_value=1_000),
            max_size=4,
        ),
        st.text(max_size=20),
        st.none(),
    ),
)
def test_flatten_optimize_uses_cost_fields_and_safe_file_count(
    policy_mode: str,
    files: object,
    cost: object,
) -> None:
    flattened = _flatten_optimize({"policy_mode": policy_mode, "files": files, "cost": cost})

    assert flattened is not None
    assert flattened["classification"] == policy_mode
    cost_map = cost if isinstance(cost, dict) else {}
    expected_files = len(files) if isinstance(files, list | tuple) else 0
    assert flattened["files_touched"] == cost_map.get("files", expected_files)
    assert flattened["changed_lines_total"] == cost_map.get("changed_lines", 0)
    assert flattened["changed_lines_outside_diff"] == cost_map.get("outside_diff", 0)
    assert flattened["risk"] == cost_map.get("risk", 0)


@given(policy_mode=st.one_of(st.none(), st.integers(), st.booleans(), st.lists(st.text())))
def test_flatten_optimize_rejects_non_string_policy_modes(policy_mode: object) -> None:
    assert _flatten_optimize({"policy_mode": policy_mode}) is None


def test_flatten_optimize_preserves_candidate_identity_fields() -> None:
    flattened = _flatten_optimize({
        "policy_mode": "auto",
        "rule": "I001",
        "patch_path": ".lintfix/patches/I001.patch",
    })

    assert flattened is not None
    assert flattened["rule"] == "I001"
    assert flattened["patch_path"] == ".lintfix/patches/I001.patch"


@given(
    found=st.booleans(),
    notice=st.integers(min_value=0, max_value=100),
    warning=st.integers(min_value=0, max_value=100),
    skip=st.integers(min_value=0, max_value=100),
)
def test_fix_annotate_payload_projects_counts(
    found: bool,
    notice: int,
    warning: int,
    skip: int,
) -> None:
    result = AnnotationResult(
        source="plan",
        path=Path(".lintfix/plan.json"),
        found=found,
        notice=notice,
        warning=warning,
        skip=skip,
    )

    payload = _fix_annotate_payload(Path(), result)

    assert payload["command"] == "fix-annotate"
    assert payload["passed"] is True
    assert payload["status"] == ("annotated" if found else "missing")
    assert payload["annotation_count"] == notice + warning
    assert payload["notice"] == notice
    assert payload["warning"] == warning
    assert payload["skip"] == skip


@given(
    auto=st.integers(min_value=0, max_value=20),
    advisory=st.integers(min_value=0, max_value=20),
    skipped=st.integers(min_value=0, max_value=20),
)
def test_collect_annotation_counts_counts_generated_plan_classes(
    auto: int,
    advisory: int,
    skipped: int,
) -> None:
    payload = {
        "candidates": [
            *[
                {"rule": f"I{index}", "classification": "auto", "files": []}
                for index in range(auto)
            ],
            *[
                {"rule": f"C{index}", "classification": "advisory", "files": []}
                for index in range(advisory)
            ],
            *[
                {"rule": f"UP{index}", "classification": "skip", "files": []}
                for index in range(skipped)
            ],
        ]
    }

    counts = _collect_annotation_counts(payload, source="plan", emit_json=True)

    assert counts == {"notice": auto, "warning": advisory, "skip": skipped}


@given(candidates=st.lists(annotation_candidates(), max_size=12))
def test_collect_annotation_counts_matches_generated_annotations(
    candidates: list[dict[str, object]],
) -> None:
    counts = _collect_annotation_counts(
        {"candidates": candidates},
        source="plan",
        emit_json=True,
    )
    annotations = [
        annotation for candidate in candidates for annotation in _annotations_for(candidate)
    ]

    assert counts == {
        "notice": sum(1 for annotation in annotations if annotation.severity == "notice"),
        "warning": sum(1 for annotation in annotations if annotation.severity == "warning"),
        "skip": sum(1 for candidate in candidates if candidate.get("classification") == "skip"),
    }
