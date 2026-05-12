"""Budgeted multi-rule fix selection (Phase 4).

Usage::

    interlocks fix-optimize                       # plan + optimize, no mutation
    interlocks fix-optimize --budget=renovation
    interlocks fix-optimize --apply               # apply selected, verify, restore on fail
    interlocks fix-optimize --stats=.lintfix/replay.json  # weight values from replay

Discovers fixable rules on the changed file set, classifies each candidate,
then runs the multi-dimensional Pareto-pruned optimizer in
:mod:`lintfix.optimize` to pick the highest-value subset that fits the
selected budget. ``--apply`` snapshots, applies the selected rules
sequentially, runs the verifier, and restores the tree on any failure.
"""

from __future__ import annotations

import json
import shlex
import sys
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from interlocks import ui
from interlocks.config import load_config
from interlocks.lintfix import budgets, escrow, verify
from interlocks.lintfix import optimize as optimize_mod
from interlocks.lintfix import plan as plan_module
from interlocks.lintfix import stats as stats_module
from interlocks.runner import arg_flag_value, arg_value, dump_and_exit

if TYPE_CHECKING:
    from pathlib import Path

_DEFAULT_VERIFY_CMD: tuple[str, ...] = ("interlocks", "ci")


def cmd_fix_optimize(
    *,
    base: str | None = None,
    budget: str | None = None,
    apply: bool | None = None,
    stats_path: str | None = None,
    verify_cmd: tuple[str, ...] | None = None,
) -> None:
    """Build a fix plan, optimize selection, optionally apply + verify."""
    base = base or arg_value("--base=", "origin/main")
    budget_name = budget or arg_value("--budget=", "unblock")
    apply = apply if apply is not None else (arg_flag_value("--apply", "1") is not None)
    stats_path = stats_path if stats_path is not None else arg_value("--stats=", "")
    verify_cmd = verify_cmd or _verify_cmd_argv()

    cfg = load_config()
    plan = plan_module.build_plan(base=base, budget_name=budget_name)

    if plan.discovery_error is not None:
        ui.row(
            "fix-optimize",
            "discover",
            "ruff failed",
            detail=f"rc={plan.discovery_error.returncode}",
            state="fail",
        )
        dump_and_exit(plan.discovery_error.returncode, "", plan.discovery_error.stderr)

    stats_map = _load_stats(stats_path, cfg.project_root)
    candidates = optimize_mod.candidates_from_plan(plan.candidates, stats_map)
    profile = budgets.profile(budget_name)
    selection = optimize_mod.optimize(candidates, profile)

    plan_by_rule = {c.classification.rule: c for c in plan.candidates}
    patch_paths = plan_module.materialize_escrow_patches(cfg.project_root, plan)
    payload = _serialize(plan, selection, patch_paths, plan_by_rule)
    out_path = _write_optimize_json(cfg.project_root, payload)

    _print_summary(plan, selection, base, budget_name, cfg.relpath(out_path))

    if not apply:
        return
    _apply_selection(cfg.project_root, plan_by_rule, selection, verify_cmd)


def _apply_selection(
    project_root: Path,
    plan_by_rule: dict[str, plan_module.PlannedCandidate],
    selection: optimize_mod.Selection,
    verify_cmd: tuple[str, ...],
) -> None:
    if not selection.selected:
        ui.row("fix-optimize", "(nothing to apply)", "ok", state="ok")
        return
    rules_and_files = tuple(
        (s.candidate.rule, plan_by_rule[s.candidate.rule].classification.metrics.files_touched)
        for s in selection.selected
    )
    result = verify.apply_many_with_verify(rules_and_files=rules_and_files, verify_cmd=verify_cmd)
    if result.applied:
        rules = ", ".join(result.applied_rules)
        ui.row("fix-optimize", rules or "(none)", "applied + verified", state="ok")
        return
    failed_patches = "\n".join(
        plan_by_rule[rule].diff_text
        for rule, _ in rules_and_files
        if plan_by_rule[rule].diff_text.strip()
    )
    if failed_patches:
        escrow.write_failed_patch(project_root, failed_patches)
    detail = f"rule={result.failed_rule}" if result.failed_rule else "verify failed; tree restored"
    ui.row("fix-optimize", "apply", detail, state="fail")
    sys.exit(result.returncode or 1)


def _serialize(
    plan: plan_module.Plan,
    selection: optimize_mod.Selection,
    patch_paths: dict[str, str],
    plan_by_rule: dict[str, plan_module.PlannedCandidate],
) -> dict[str, Any]:
    return {
        "base": plan.base,
        "head": plan.head,
        "budget": selection.budget_name,
        "ruff_version": plan.ruff_version,
        "total_value": selection.total_value,
        "total_cost": asdict(selection.total_cost),
        "selected": [
            _serialize_candidate(s.candidate, patch_paths, plan_by_rule, reason=None)
            for s in selection.selected
        ],
        "not_selected": [
            _serialize_candidate(r.candidate, patch_paths, plan_by_rule, reason=r.reason)
            for r in selection.rejected
        ],
    }


def _serialize_candidate(
    c: optimize_mod.Candidate,
    patch_paths: dict[str, str],
    plan_by_rule: dict[str, plan_module.PlannedCandidate],
    *,
    reason: str | None,
) -> dict[str, Any]:
    planned = plan_by_rule.get(c.rule)
    return {
        "rule": c.rule,
        "value": c.value,
        "cost": asdict(c.cost),
        "policy_mode": c.policy_mode,
        "unsafe": c.unsafe,
        "files": list(c.files),
        "patch_path": patch_paths.get(c.rule),
        "reason": reason,
        "diagnostic_count": planned.diagnostic_count if planned else 0,
    }


def _print_summary(
    plan: plan_module.Plan,
    selection: optimize_mod.Selection,
    base: str,
    budget_name: str,
    out_rel: str,
) -> None:
    ui.section(f"fix-optimize ({base}, budget={budget_name})")
    if not plan.candidates:
        ui.row("fix-optimize", "(no candidates)", "ok", state="ok")
        ui.kv_block([("plan", out_rel)])
        return

    if selection.selected:
        ui.section("SELECTED")
        ui.kv_block(
            [(s.candidate.rule, _candidate_line(s.candidate)) for s in selection.selected],
            indent="  ",
        )
    else:
        ui.row("fix-optimize", "selected", "(none)", state="ok")

    if selection.rejected:
        ui.section("NOT SELECTED")
        ui.kv_block(
            [
                (r.candidate.rule, f"{_candidate_line(r.candidate)}  {r.reason}")
                for r in selection.rejected
            ],
            indent="  ",
        )

    ui.section("plan")
    ui.kv_block([
        ("path", out_rel),
        ("selected", str(len(selection.selected))),
        ("total value", str(selection.total_value)),
        (
            "total cost",
            f"outside={selection.total_cost.outside_diff}  "
            f"lines={selection.total_cost.changed_lines}  "
            f"files={selection.total_cost.files}  "
            f"risk={selection.total_cost.risk}",
        ),
    ])


def _candidate_line(c: optimize_mod.Candidate) -> str:
    return (
        f"value={c.value}  "
        f"cost={{outside={c.cost.outside_diff}, lines={c.cost.changed_lines}, "
        f"files={c.cost.files}, risk={c.cost.risk}}}"
    )


def _load_stats(path: str, project_root: Path) -> dict[str, stats_module.RuleStats] | None:
    """Load per-rule stats from ``replay.json`` if it exists at ``path``."""
    if not path:
        return None
    target = project_root / path
    if not target.is_file():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    rows = payload.get("rules", [])
    out: dict[str, stats_module.RuleStats] = {}
    for row in rows:
        try:
            out[row["rule"]] = stats_module.RuleStats(**row)
        except (TypeError, KeyError):
            continue
    return out


def _write_optimize_json(project_root: Path, payload: dict[str, Any]) -> Path:
    target = escrow.lintfix_dir(project_root) / "optimize.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _verify_cmd_argv() -> tuple[str, ...]:
    raw = arg_value("--verify-cmd=", "")
    if raw:
        return tuple(shlex.split(raw))
    return _DEFAULT_VERIFY_CMD
