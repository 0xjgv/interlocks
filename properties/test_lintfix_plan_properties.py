"""Property tests for lintfix planning helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import patch

from hypothesis import given
from hypothesis import strategies as st

from interlocks.lintfix import discover
from interlocks.lintfix import plan as plan_module
from interlocks.lintfix.budgets import UNBLOCK, Budget, CandidateCost
from interlocks.lintfix.classify import CandidateMetrics, Classification
from interlocks.lintfix.simulate import CandidatePatch

if TYPE_CHECKING:
    from interlocks.lintfix.rules import Mode, MutationClass

_SEGMENT = st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,10}", fullmatch=True)
_FILE = st.lists(_SEGMENT, min_size=1, max_size=4).map(lambda parts: "/".join(parts) + ".py")
_RULE = st.from_regex(r"[A-Z][A-Z0-9]{1,6}", fullmatch=True)
_MODE = st.sampled_from(("auto", "escrow", "advisory", "skip"))
_MUTATION_CLASS = st.sampled_from((
    "import_sort",
    "eof_newline",
    "import_delete",
    "unused_variable",
    "type_annotation_rewrite",
    "collection_rewrite",
    "control_flow_or_style",
    "broad_modernization",
    "other",
))
_LINE = st.from_regex(r"[A-Za-z0-9_ ,=+\-]{0,30}", fullmatch=True)


def _format_diff(file: str, old: str, new: str) -> str:
    return f"--- a/{file}\n+++ b/{file}\n@@ -1,1 +1,1 @@\n-{old}\n+{new}\n"


def _budget() -> Budget:
    return Budget(
        name="generated",
        max_files=UNBLOCK.max_files,
        max_changed_lines=UNBLOCK.max_changed_lines,
        max_outside_diff_lines=UNBLOCK.max_outside_diff_lines,
        max_risk=UNBLOCK.max_risk,
    )


@given(file=_FILE)
def test_format_candidate_for_empty_diff_is_skip_with_file_fallback(file: str) -> None:
    with patch.object(
        plan_module.simulate,
        "simulate_format",
        return_value=CandidatePatch(f"FORMAT:{file}", (file,), "", 0),
    ):
        candidate = plan_module._format_candidate_for(file, {})

    assert candidate.kind == "format"
    assert candidate.classification.rule == f"FORMAT:{file}"
    assert candidate.classification.mode == "skip"
    assert candidate.classification.metrics.files_touched == (file,)
    assert candidate.classification.metrics.changed_lines_total == 0
    assert candidate.classification.reason == "patch is empty"


@given(file=_FILE, old=_LINE, new=_LINE)
def test_format_candidate_for_nonempty_diff_is_auto(file: str, old: str, new: str) -> None:
    diff_text = _format_diff(file, old, new)
    with patch.object(
        plan_module.simulate,
        "simulate_format",
        return_value=CandidatePatch(f"FORMAT:{file}", (file,), diff_text, 0),
    ):
        candidate = plan_module._format_candidate_for(file, {})

    assert candidate.kind == "format"
    assert candidate.classification.rule == f"FORMAT:{file}"
    assert candidate.classification.mode == "auto"
    assert candidate.classification.metrics.files_touched == (file,)
    assert candidate.classification.metrics.changed_lines_total == 2
    assert candidate.diff_text == diff_text


@given(file=_FILE, old=_LINE, new=_LINE)
def test_format_candidate_for_preserves_format_candidate_defaults(
    file: str,
    old: str,
    new: str,
) -> None:
    with patch.object(
        plan_module.simulate,
        "simulate_format",
        return_value=CandidatePatch(f"FORMAT:{file}", (file,), _format_diff(file, old, new), 0),
    ):
        candidate = plan_module._format_candidate_for(file, {})

    assert candidate.unsafe is False
    assert candidate.diagnostic_count == 1
    assert candidate.mutation_class == "other"
    assert candidate.kind == "format"


@given(rule=_RULE, files=st.lists(_FILE, min_size=1, max_size=5, unique=True).map(tuple))
def test_candidate_for_unsafe_only_rules_never_simulates(
    rule: str, files: tuple[str, ...]
) -> None:
    rule_candidate = discover.RuleCandidate(
        rule=rule,
        files=files,
        has_safe_fix=False,
        has_unsafe_fix=True,
        diagnostic_count=len(files),
    )
    with patch.object(
        plan_module.simulate,
        "simulate_rule",
        side_effect=AssertionError("unsafe-only rules must not be simulated"),
    ):
        candidate = plan_module._candidate_for(rule_candidate, {}, _budget())

    assert candidate.classification.rule == rule
    assert candidate.classification.mode == "skip"
    assert not candidate.diff_text
    assert candidate.unsafe is True
    assert candidate.diagnostic_count == len(files)


@given(
    rule=_RULE,
    files=st.lists(_FILE, min_size=1, max_size=5, unique=True).map(tuple),
    old=_LINE,
    new=_LINE,
    diagnostic_count=st.integers(min_value=0, max_value=100),
    has_unsafe_fix=st.booleans(),
)
def test_candidate_for_safe_rules_uses_simulated_patch(
    rule: str,
    files: tuple[str, ...],
    old: str,
    new: str,
    diagnostic_count: int,
    has_unsafe_fix: bool,
) -> None:
    diff_text = _format_diff(files[0], old, new)
    rule_candidate = discover.RuleCandidate(
        rule=rule,
        files=files,
        has_safe_fix=True,
        has_unsafe_fix=has_unsafe_fix,
        diagnostic_count=diagnostic_count,
    )
    with patch.object(
        plan_module.simulate,
        "simulate_rule",
        return_value=CandidatePatch(rule, files, diff_text, 0),
    ) as simulate_rule:
        candidate = plan_module._candidate_for(rule_candidate, {}, _budget())

    simulate_rule.assert_called_once_with(rule, files)
    assert candidate.classification.rule == rule
    assert candidate.diff_text == diff_text
    assert candidate.unsafe is False
    assert candidate.diagnostic_count == diagnostic_count


@given(
    rule=_RULE,
    mode=_MODE,
    mutation_class=_MUTATION_CLASS,
    files=st.lists(_FILE, max_size=5, unique=True).map(tuple),
    changed_total=st.integers(min_value=0, max_value=500),
    changed_inside=st.integers(min_value=0, max_value=500),
    changed_outside=st.integers(min_value=0, max_value=500),
    risk=st.integers(min_value=0, max_value=100),
    diagnostic_count=st.integers(min_value=0, max_value=100),
    unsafe=st.booleans(),
)
def test_serialize_preserves_candidate_shape_and_metrics(
    rule: str,
    mode: str,
    mutation_class: str,
    files: tuple[str, ...],
    changed_total: int,
    changed_inside: int,
    changed_outside: int,
    risk: int,
    diagnostic_count: int,
    unsafe: bool,
) -> None:
    classification = Classification(
        rule=rule,
        mode=cast("Mode", mode),
        metrics=CandidateMetrics(files, changed_total, changed_inside, changed_outside, 0, 0),
        cost=CandidateCost(len(files), changed_total, changed_outside, risk),
        reason=None if mode == "auto" else "generated",
        patch_id=f"{rule}:generated",
    )
    candidate = plan_module.PlannedCandidate(
        classification=classification,
        diff_text="diff",
        unsafe=unsafe,
        diagnostic_count=diagnostic_count,
        mutation_class=cast("MutationClass", mutation_class),
    )
    plan = plan_module.Plan(
        base="base",
        head="head",
        budget="unblock",
        ruff_version="0.0.0",
        candidates=(candidate,),
        discovery_error=None,
        author_cost=7,
    )

    payload = plan_module.serialize(plan, patch_paths={rule: ".lintfix/escrow/generated.patch"})
    [serialized] = payload["candidates"]

    assert serialized["id"] == f"{rule}:generated"
    assert serialized["rule"] == rule
    assert serialized["mode"] == mode
    assert serialized["classification"] == mode
    assert serialized["mutation_class"] == mutation_class
    assert serialized["files_touched"] == len(files)
    assert serialized["files"] == list(files)
    assert serialized["changed_lines_total"] == changed_total
    assert serialized["changed_lines_inside_diff"] == changed_inside
    assert serialized["changed_lines_outside_diff"] == changed_outside
    assert serialized["risk"] == risk
    assert serialized["diagnostic_count"] == diagnostic_count
    assert serialized["unsafe"] is unsafe
    assert serialized["patch_path"] == ".lintfix/escrow/generated.patch"


@given(base=_RULE, head=_RULE, budget=_RULE, author_cost=st.integers(min_value=0, max_value=500))
def test_serialize_preserves_empty_plan_header(
    base: str,
    head: str,
    budget: str,
    author_cost: int,
) -> None:
    plan = plan_module.Plan(
        base=base,
        head=head,
        budget=budget,
        ruff_version="0.0.0",
        candidates=(),
        discovery_error=None,
        author_cost=author_cost,
    )

    payload = plan_module.serialize(plan)

    assert payload == {
        "base": base,
        "head": head,
        "mode": budget,
        "author_cost": author_cost,
        "ruff_version": "0.0.0",
        "candidates": [],
    }


@given(patch_paths=st.dictionaries(_RULE, _FILE, max_size=5))
def test_serialize_empty_plan_ignores_patch_path_map(patch_paths: dict[str, str]) -> None:
    plan = plan_module.Plan(
        base="base",
        head="head",
        budget="unblock",
        ruff_version="0.0.0",
        candidates=(),
        discovery_error=None,
        author_cost=0,
    )

    payload = plan_module.serialize(plan, patch_paths=patch_paths)

    assert payload["candidates"] == []
