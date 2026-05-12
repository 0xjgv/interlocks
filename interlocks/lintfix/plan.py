"""Fix-plan orchestrator: discover → simulate → classify → serialize.

Non-mutating: every candidate is materialized as a unified diff via
``ruff --diff``; no candidate is ever applied here. The output is a
:class:`Plan` value and a JSON file at ``.lintfix/plan.json``.

The classifier (``lintfix.classify``) already handles budget downgrades and
risk scoring. This module's job is the outer loop and the serialization.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from interlocks.config import load_config
from interlocks.lintfix import budgets, classify, diff, discover, escrow, rules, simulate

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class DiscoveryError:
    """Ruff discovery returned a fatal rc (>=2) instead of diagnostics."""

    returncode: int
    stderr: str


@dataclass(frozen=True)
class PlannedCandidate:
    """One classified candidate, plus the patch text it was measured from.

    ``mutation_class`` is denormalized off ``rules.policy_for`` so serializers
    don't have to re-walk the rule catalog per candidate.
    """

    classification: classify.Classification
    diff_text: str
    unsafe: bool
    diagnostic_count: int
    mutation_class: rules.MutationClass


@dataclass(frozen=True)
class Plan:
    """Outcome of one fix-plan run."""

    base: str
    head: str
    budget: str
    ruff_version: str
    candidates: tuple[PlannedCandidate, ...]
    discovery_error: DiscoveryError | None


def build_plan(*, base: str, budget_name: str) -> Plan:
    """Run the full plan pipeline and return the result.

    Each candidate rule is simulated in isolation over the file subset where
    it actually triggered (from ruff's JSON output) — not the full changed
    set. Rules whose only available fix is unsafe are classified as ``skip``
    via the shared ``classify.classify(unsafe=True)`` path.
    """
    cfg = load_config()
    ruff_version = cfg.tool_version("ruff")
    head = diff.head_sha()
    base_sha = diff.resolve_base(base)
    if not base_sha:
        return _empty_plan(base, head, budget_name, ruff_version)

    files = diff.changed_files(base_sha)
    if not files:
        return _empty_plan(base, head, budget_name, ruff_version)

    discovery = discover.discover_fixable_rules(files)
    if discovery.returncode >= 2:
        return _empty_plan(
            base,
            head,
            budget_name,
            ruff_version,
            error=DiscoveryError(discovery.returncode, discovery.stderr),
        )

    hunks = diff.changed_hunks(base_sha, files)
    profile = budgets.profile(budget_name)
    candidates = tuple(_candidate_for(rc, hunks, profile) for rc in discovery.candidates)

    return Plan(
        base=base,
        head=head,
        budget=budget_name,
        ruff_version=ruff_version,
        candidates=candidates,
        discovery_error=None,
    )


def _empty_plan(
    base: str,
    head: str,
    budget_name: str,
    ruff_version: str,
    *,
    error: DiscoveryError | None = None,
) -> Plan:
    return Plan(base, head, budget_name, ruff_version, (), error)


def _candidate_for(
    rule_candidate: discover.RuleCandidate,
    hunks: dict[str, diff.FileHunks],
    profile: budgets.Budget,
) -> PlannedCandidate:
    policy = rules.policy_for(rule_candidate.rule)
    unsafe_only = rule_candidate.has_unsafe_fix and not rule_candidate.has_safe_fix
    if unsafe_only:
        classification = classify.classify(
            patch_text="",
            diff_hunks={},
            policy=policy,
            budget=profile,
            unsafe=True,
        )
        return PlannedCandidate(
            classification=classification,
            diff_text="",
            unsafe=True,
            diagnostic_count=rule_candidate.diagnostic_count,
            mutation_class=policy.mutation_class,
        )
    patch = simulate.simulate_rule(rule_candidate.rule, rule_candidate.files)
    classification = classify.classify(
        patch_text=patch.diff,
        diff_hunks=hunks,
        policy=policy,
        budget=profile,
    )
    return PlannedCandidate(
        classification=classification,
        diff_text=patch.diff,
        unsafe=False,
        diagnostic_count=rule_candidate.diagnostic_count,
        mutation_class=policy.mutation_class,
    )


def serialize(plan: Plan, *, patch_paths: dict[str, str] | None = None) -> dict[str, Any]:
    """Render :class:`Plan` as a JSON-ready dict.

    ``patch_paths`` maps ``rule`` to a relative patch path for candidates whose
    diff text was materialized as an escrow file. Pass ``None`` to omit the
    field on every candidate.
    """
    paths = patch_paths or {}
    return {
        "base": plan.base,
        "head": plan.head,
        "mode": plan.budget,
        "ruff_version": plan.ruff_version,
        "candidates": [_serialize_candidate(c, paths) for c in plan.candidates],
    }


def _serialize_candidate(c: PlannedCandidate, paths: dict[str, str]) -> dict[str, Any]:
    cls = c.classification
    m = cls.metrics
    return {
        "id": cls.patch_id,
        "rule": cls.rule,
        "mode": cls.mode,
        "classification": cls.mode,
        "mutation_class": c.mutation_class,
        "files_touched": len(m.files_touched),
        "files": list(m.files_touched),
        "changed_lines_total": m.changed_lines_total,
        "changed_lines_inside_diff": m.changed_lines_inside_diff,
        "changed_lines_outside_diff": m.changed_lines_outside_diff,
        "risk": cls.cost.risk,
        "diagnostic_count": c.diagnostic_count,
        "unsafe": c.unsafe,
        "patch_path": paths.get(cls.rule),
        "reason": cls.reason,
    }


def write_plan_json(project_root: Path, payload: dict[str, Any]) -> Path:
    """Write ``payload`` to ``.lintfix/plan.json`` (creates parent dirs)."""
    target = escrow.lintfix_dir(project_root) / "plan.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def materialize_escrow_patches(project_root: Path, plan: Plan) -> dict[str, str]:
    """Write escrow/advisory patches and return ``{rule: relative_path}``.

    ``auto`` candidates pass budgets and stay non-materialized in plan mode —
    they're meant to be applied via ``fix-rule --apply``, not stockpiled.
    ``skip`` candidates have no diff to write.
    """
    paths: dict[str, str] = {}
    for candidate in plan.candidates:
        cls = candidate.classification
        if cls.mode not in ("escrow", "advisory"):
            continue
        if not candidate.diff_text.strip():
            continue
        target = escrow.write_patch(project_root, cls.rule, candidate.diff_text)
        paths[cls.rule] = str(target.relative_to(project_root))
    return paths
