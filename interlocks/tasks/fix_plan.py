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

from typing import TYPE_CHECKING

from interlocks import ui
from interlocks.config import load_config
from interlocks.lintfix import plan as plan_module
from interlocks.runner import arg_value, dump_and_exit

if TYPE_CHECKING:
    from interlocks.lintfix.rules import Mode

_GROUP_ORDER: tuple[tuple[Mode, str], ...] = (
    ("auto", "AUTO-APPLY ELIGIBLE"),
    ("escrow", "PATCH ESCROW"),
    ("advisory", "ADVISORY"),
    ("skip", "SKIPPED"),
)


def cmd_fix_plan(
    *,
    base: str | None = None,
    budget: str | None = None,
) -> None:
    """Build a fix plan (non-mutating). Falls back to argv when args omitted."""
    base = base or arg_value("--base=", "origin/main")
    budget_name = budget or arg_value("--budget=", "unblock")

    cfg = load_config()
    plan = plan_module.build_plan(base=base, budget_name=budget_name)

    if plan.discovery_error is not None:
        ui.row(
            "fix-plan",
            "discover",
            "ruff failed",
            detail=f"rc={plan.discovery_error.returncode}",
            state="fail",
        )
        dump_and_exit(plan.discovery_error.returncode, "", plan.discovery_error.stderr)

    patch_paths = plan_module.materialize_escrow_patches(cfg.project_root, plan)
    payload = plan_module.serialize(plan, patch_paths=patch_paths)
    plan_path = plan_module.write_plan_json(cfg.project_root, payload)

    _print_plan(plan, base, budget_name, cfg.relpath(plan_path))


def _print_plan(plan: plan_module.Plan, base: str, budget_name: str, plan_rel: str) -> None:
    ui.section(f"fix-plan ({base}, budget={budget_name})")
    if not plan.candidates:
        ui.row("fix-plan", "(no candidates)", "ok", state="ok")
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
