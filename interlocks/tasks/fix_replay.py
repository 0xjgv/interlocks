"""Offline replay of the fix-planner across recent commits.

Usage::

    interlocks fix-replay                       # last 25 commits on origin/main
    interlocks fix-replay --base=main --n=10
    interlocks fix-replay --budget=renovation

Drives ``interlocks fix-plan`` against each of the last N first-parent
commits on ``base`` in a temporary git worktree, aggregates per-rule
statistics, computes a Pareto frontier, and writes
``.lintfix/replay.json``. Never mutates the working tree.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from interlocks import ui
from interlocks.config import load_config
from interlocks.lintfix import escrow
from interlocks.lintfix import replay as replay_module
from interlocks.lintfix import stats as stats_module
from interlocks.runner import arg_value

if TYPE_CHECKING:
    from pathlib import Path


def cmd_fix_replay(
    *,
    base: str | None = None,
    n: int | None = None,
    budget: str | None = None,
) -> None:
    """Replay the planner across the last ``n`` commits on ``base``.

    Falls back to argv when called bare so the CLI dispatcher signature is
    consistent with the other ``fix-*`` tasks.
    """
    base = base or arg_value("--base=", "origin/main")
    budget_name = budget or arg_value("--budget=", "unblock")
    n_value = n if n is not None else int(arg_value("--n=", "25"))

    cfg = load_config()
    result = replay_module.replay_history(
        base_branch=base,
        n=n_value,
        budget_name=budget_name,
        repo_root=cfg.project_root,
    )

    samples = tuple(s for p in result.points for s in p.samples)
    rule_stats = stats_module.aggregate(samples)
    payload = _serialize(result, rule_stats)
    plan_path = _write_replay_json(cfg.project_root, payload)

    _print_summary(result, rule_stats, base, budget_name, cfg.relpath(plan_path))


def _serialize(
    result: replay_module.ReplayResult,
    rule_stats: tuple[stats_module.RuleStats, ...],
) -> dict[str, Any]:
    return {
        "base_branch": result.base_branch,
        "budget": result.budget_name,
        "n_requested": result.requested,
        "n_replayed": len(result.points),
        "n_with_error": sum(1 for p in result.points if p.error),
        "commits": [_serialize_point(p) for p in result.points],
        "rules": [asdict(s) for s in sorted(rule_stats, key=_rule_sort_key)],
    }


def _serialize_point(point: replay_module.ReplayPoint) -> dict[str, Any]:
    return {
        "commit": point.commit,
        "parent": point.parent,
        "samples": [asdict(s) for s in point.samples],
        "error": point.error,
        "reverted_in": point.reverted_in,
    }


def _rule_sort_key(stat: stats_module.RuleStats) -> tuple[int, int, str]:
    """Sort: promotion candidates first, then by PRs helped desc, then rule code."""
    promotion_rank = {"auto": 0, "escrow": 1, "advisory": 2, "skip": 3, "needs_data": 4}
    rank = promotion_rank.get(str(stat.recommended_mode), 5)
    return (rank, -stat.prs_helped, stat.rule)


def _write_replay_json(project_root: Path, payload: dict[str, Any]) -> Path:
    target = escrow.lintfix_dir(project_root) / "replay.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _print_summary(
    result: replay_module.ReplayResult,
    rule_stats: tuple[stats_module.RuleStats, ...],
    base: str,
    budget_name: str,
    plan_rel: str,
) -> None:
    header = f"fix-replay ({base}, n={result.requested}, budget={budget_name})"
    ui.section(header)
    errors = sum(1 for p in result.points if p.error)
    ui.kv_block([
        ("commits replayed", str(len(result.points))),
        ("commits with errors", str(errors)),
        ("rules observed", str(len(rule_stats))),
    ])

    if not rule_stats:
        ui.row("fix-replay", "(no candidates observed)", "ok", state="ok")
        ui.kv_block([("plan", plan_rel)])
        return

    groups: dict[str, list[stats_module.RuleStats]] = {
        "PROMOTE": [],
        "DEMOTE": [],
        "KEEP": [],
        "NEEDS DATA": [],
    }
    for s in sorted(rule_stats, key=_rule_sort_key):
        groups[_bucket(s)].append(s)

    for label, bucket in groups.items():
        if not bucket:
            continue
        ui.section(label)
        ui.kv_block([(s.rule, _summary_line(s)) for s in bucket], indent="  ")

    frontier = [s.rule for s in rule_stats if s.on_pareto_frontier]
    ui.section("pareto frontier")
    ui.kv_block([("rules", ", ".join(sorted(frontier)) or "(empty)")])
    ui.section("plan")
    ui.kv_block([("path", plan_rel)])


def _bucket(stat: stats_module.RuleStats) -> str:
    if stat.recommended_mode == "needs_data":
        return "NEEDS DATA"
    if stat.recommended_mode == stat.current_mode:
        return "KEEP"
    promote_order = {"skip": 0, "advisory": 1, "escrow": 2, "auto": 3}
    current = promote_order.get(stat.current_mode, 0)
    recommended = promote_order.get(str(stat.recommended_mode), 0)
    return "PROMOTE" if recommended > current else "DEMOTE"


def _summary_line(stat: stats_module.RuleStats) -> str:
    parts = [
        f"{stat.prs_helped}/{stat.prs_with_candidate} PRs",
        f"p95 outside-diff={stat.p95_outside_diff_lines:g}",
        f"current={stat.current_mode}",
        f"rec={stat.recommended_mode}",
    ]
    if stat.unsafe_seen:
        parts.append("unsafe-seen")
    if stat.revert_signal:
        parts.append(f"reverts={stat.revert_signal}")
    if stat.rationale:
        parts.append(stat.rationale)
    return "  ".join(parts)
