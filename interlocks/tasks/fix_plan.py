"""Non-mutating fix-plan command.

Usage::

    interlocks fix-plan                    # plan vs origin/main, unblock budget
    interlocks fix-plan --base=main
    interlocks fix-plan --budget=renovation

Discovers every fixable ruff rule on the changed file set, simulates each
in isolation, classifies the candidate patch, writes ``.lintfix/plan.json``,
and prints a grouped summary. Never mutates the working tree.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from interlocks import ui
from interlocks.config import load_config
from interlocks.lintfix import plan as plan_module
from interlocks.runner import arg_value, dump_and_exit

if TYPE_CHECKING:
    from interlocks.config import InterlockConfig
    from interlocks.lintfix.rules import Mode

_GROUP_ORDER: tuple[tuple[Mode, str], ...] = (
    ("auto", "AUTO-APPLY ELIGIBLE"),
    ("escrow", "PATCH ESCROW"),
    ("advisory", "ADVISORY"),
    ("skip", "SKIPPED"),
)


@runtime_checkable
class _HasReturncode(Protocol):
    returncode: object


def cmd_fix_plan(
    *,
    base: str | None = None,
    budget: str | None = None,
) -> None:
    """Build a fix plan (non-mutating). Falls back to argv when args omitted."""
    base, budget_name = _resolve_inputs(base, budget)
    cfg = load_config()
    plan = plan_module.build_plan(base=base, budget_name=budget_name)
    _exit_if_discovery_failed(plan)
    plan_rel = _write_plan_artifacts(cfg, plan)
    _render_plan(plan, base, budget_name, plan_rel)


def _resolve_inputs(base: str | None, budget: str | None) -> tuple[str, str]:
    return (
        base or arg_value("--base=", "origin/main"),
        budget or arg_value("--budget=", "unblock"),
    )


def _exit_if_discovery_failed(plan: plan_module.Plan) -> None:
    if plan.discovery_error is None:
        return
    if ui.is_json():
        ui.print_json(_fix_plan_error_payload(plan.discovery_error))
        sys.exit(plan.discovery_error.returncode)
    ui.row(
        "fix-plan",
        "discover",
        "ruff failed",
        detail=f"rc={plan.discovery_error.returncode}",
        state="fail",
    )
    dump_and_exit(plan.discovery_error.returncode, "", plan.discovery_error.stderr)


def _write_plan_artifacts(cfg: InterlockConfig, plan: plan_module.Plan) -> str:
    patch_paths = plan_module.materialize_escrow_patches(cfg.project_root, plan)
    payload = plan_module.serialize(plan, patch_paths=patch_paths)
    plan_path = plan_module.write_plan_json(cfg.project_root, payload)
    return cfg.relpath(plan_path)


def _render_plan(plan: plan_module.Plan, base: str, budget_name: str, plan_rel: str) -> None:
    if ui.is_json():
        ui.print_json(_fix_plan_payload(plan, base, budget_name, plan_rel))
        return
    _print_plan(plan, base, budget_name, plan_rel)


def _print_plan(plan: plan_module.Plan, base: str, budget_name: str, plan_rel: str) -> None:
    ui.gate_row(
        "fix-plan",
        plan_rel,
        "ok",
        detail=f"{len(plan.candidates)} candidate(s), base={base}, budget={budget_name}",
        state="ok",
    )
    ui.section(f"fix-plan ({base}, budget={budget_name})")
    if not plan.candidates:
        ui.kv_block([("plan", plan_rel)])
        return

    grouped: dict[Mode, list[plan_module.PlannedCandidate]] = {
        mode: [] for mode, _ in _GROUP_ORDER
    }
    for c in plan.candidates:
        grouped.setdefault(c.classification.mode, []).append(c)

    for mode, header in _GROUP_ORDER:
        bucket = grouped.get(mode) or []
        if not bucket:
            continue
        ui.section(header)
        ui.kv_block([(c.classification.rule, _summary(c)) for c in bucket], indent="  ")

    ui.section("plan")
    ui.kv_block([
        ("path", plan_rel),
        ("candidates", str(len(plan.candidates))),
        ("ruff", plan.ruff_version),
    ])


def _summary(c: plan_module.PlannedCandidate) -> str:
    m = c.classification.metrics
    parts = [
        f"{len(m.files_touched)} files",
        f"{m.changed_lines_total} lines",
        f"{m.changed_lines_outside_diff} outside-diff",
        f"risk={c.classification.cost.risk}",
    ]
    if c.classification.reason:
        parts.append(c.classification.reason)
    return "  ".join(parts)


def _fix_plan_payload(
    plan: plan_module.Plan,
    base: str,
    budget_name: str,
    plan_path: str,
) -> dict[str, object]:
    return {
        "command": "fix-plan",
        "passed": True,
        "status": "planned",
        "base": base,
        "budget": budget_name,
        "plan_path": plan_path,
        "candidate_count": len(plan.candidates),
        "by_classification": _classification_counts(plan),
        "ruff_version": plan.ruff_version,
    }


def _classification_counts(plan: plan_module.Plan) -> dict[str, int]:
    counts = {mode: 0 for mode, _ in _GROUP_ORDER}
    for candidate in plan.candidates:
        counts[candidate.classification.mode] = counts.get(candidate.classification.mode, 0) + 1
    return counts


def _fix_plan_error_payload(error: object) -> dict[str, object]:
    returncode = _error_returncode(error)
    stderr = getattr(error, "stderr", "")
    return {
        "command": "fix-plan",
        "passed": False,
        "status": "discovery-failed",
        "returncode": returncode,
        "stderr_excerpt": _stderr_excerpt(stderr),
    }


def _error_returncode(error: object) -> int:
    if not isinstance(error, _HasReturncode):
        return 1
    returncode = error.returncode
    if isinstance(returncode, int):
        return returncode
    return 1


def _stderr_excerpt(stderr: object) -> str:
    text = str(stderr)
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines[:20])
