"""Generated-input checks for fix-plan JSON helpers."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from hypothesis import given
from hypothesis import strategies as st

from interlocks.lintfix import plan as plan_module
from interlocks.lintfix.budgets import CandidateCost
from interlocks.lintfix.classify import CandidateMetrics, Classification
from interlocks.tasks.fix_plan import (
    _classification_counts,
    _fix_plan_payload,
    _resolve_inputs,
    _stderr_excerpt,
)

if TYPE_CHECKING:
    from interlocks.lintfix.rules import Mode

_MODES = st.sampled_from(["auto", "escrow", "advisory", "skip"])
_ARG = st.text(
    alphabet=st.characters(blacklist_characters="\r\n"),
    min_size=1,
    max_size=20,
)


def _candidate(mode: Mode, index: int) -> plan_module.PlannedCandidate:
    metrics = CandidateMetrics(
        files_touched=(f"file{index}.py",),
        changed_lines_total=1,
        changed_lines_inside_diff=1,
        changed_lines_outside_diff=0,
        comment_deletes=0,
        control_flow_edits=0,
    )
    classification = Classification(
        rule=f"R{index}",
        mode=mode,
        metrics=metrics,
        cost=CandidateCost(
            files_touched=1,
            changed_lines_total=1,
            changed_lines_outside_diff=0,
            risk=0,
        ),
        reason=None,
        patch_id=f"R{index}:file{index}.py",
    )
    return plan_module.PlannedCandidate(
        classification=classification,
        diff_text="diff",
        unsafe=False,
        diagnostic_count=1,
        mutation_class="generated",
    )


def _plan(modes: list[Mode]) -> plan_module.Plan:
    return plan_module.Plan(
        base="HEAD",
        head="abc",
        budget="unblock",
        ruff_version="0.x",
        candidates=tuple(_candidate(mode, index) for index, mode in enumerate(modes)),
        discovery_error=None,
    )


@given(
    explicit_base=st.one_of(st.none(), _ARG),
    explicit_budget=st.one_of(st.none(), _ARG),
    argv_base=st.one_of(st.none(), _ARG),
    argv_budget=st.one_of(st.none(), _ARG),
)
def test_resolve_inputs_prefers_explicit_then_cli_then_defaults(
    explicit_base: str | None,
    explicit_budget: str | None,
    argv_base: str | None,
    argv_budget: str | None,
) -> None:
    argv = ["interlocks", "fix plan"]
    if argv_base is not None:
        argv.append(f"--base={argv_base}")
    if argv_budget is not None:
        argv.append(f"--budget={argv_budget}")
    old_argv = sys.argv
    sys.argv = argv
    try:
        resolved = _resolve_inputs(explicit_base, explicit_budget)
    finally:
        sys.argv = old_argv

    assert resolved == (
        explicit_base or argv_base or "origin/main",
        explicit_budget or argv_budget or "unblock",
    )


@given(explicit_base=_ARG, explicit_budget=_ARG, argv_base=_ARG, argv_budget=_ARG)
def test_resolve_inputs_explicit_values_override_cli_values(
    explicit_base: str,
    explicit_budget: str,
    argv_base: str,
    argv_budget: str,
) -> None:
    old_argv = sys.argv
    sys.argv = ["interlocks", "fix plan", f"--base={argv_base}", f"--budget={argv_budget}"]
    try:
        assert _resolve_inputs(explicit_base, explicit_budget) == (
            explicit_base,
            explicit_budget,
        )
    finally:
        sys.argv = old_argv


@given(argv_base=_ARG, argv_budget=_ARG)
def test_resolve_inputs_empty_explicit_values_fall_back_to_cli(
    argv_base: str,
    argv_budget: str,
) -> None:
    old_argv = sys.argv
    sys.argv = ["interlocks", "fix plan", f"--base={argv_base}", f"--budget={argv_budget}"]
    try:
        assert _resolve_inputs("", "") == (argv_base, argv_budget)
    finally:
        sys.argv = old_argv


@given(modes=st.lists(_MODES, max_size=30))
def test_fix_plan_payload_counts_generated_classifications(modes: list[Mode]) -> None:
    plan = _plan(modes)
    payload = _fix_plan_payload(plan, "HEAD", "unblock", ".lintfix/plan.json")

    assert payload["command"] == "fix plan"
    assert payload["passed"] is True
    assert payload["candidate_count"] == len(modes)
    assert payload["by_classification"] == _classification_counts(plan)
    for mode in ("auto", "escrow", "advisory", "skip"):
        assert payload["by_classification"][mode] == modes.count(mode)


@given(lines=st.lists(st.text(" abcdef0123456789", min_size=1, max_size=30), max_size=40))
def test_stderr_excerpt_keeps_first_twenty_nonblank_lines(lines: list[str]) -> None:
    stderr = "\n\n".join(lines)
    nonblank = [line for line in lines if line.strip()]

    assert _stderr_excerpt(stderr) == "\n".join(nonblank[:20])
