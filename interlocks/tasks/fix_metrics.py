"""Aggregate metrics across `.lintfix/` outputs (Phase 5).

Reads ``.lintfix/plan.json``, ``.lintfix/optimize.json``, and
``.lintfix/replay.json`` (each optional), rolls them up into per-rule and
per-run aggregates, and writes ``.lintfix/metrics.json`` plus a human summary.

The schema is designed to be picked up by CI: each run uploads
``.lintfix/`` as an artifact; cross-run aggregation happens externally by
collecting the per-run ``metrics.json`` files. There is no persistent
counter inside interlocks itself — keeping the tool stateless makes the
metrics auditable and prevents per-author tracking by accident.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from interlocks import ui
from interlocks.config import load_config, relpath
from interlocks.lintfix import escrow
from interlocks.lintfix.stats import quantile

if TYPE_CHECKING:
    from pathlib import Path


def cmd_fix_metrics() -> None:
    """Aggregate `.lintfix/*.json` into one metrics report."""
    project_root = load_config().project_root
    out_path = aggregate_metrics(project_root)
    if ui.is_json():
        ui.print_json(_fix_metrics_payload(project_root, out_path))


def aggregate_metrics(project_root: Path) -> Path:
    """Roll up `.lintfix/{plan,optimize,replay}.json` into `metrics.json`.

    The single implementation behind both ``fix-metrics`` and the inline
    ``fix-optimize --metrics`` path: it reads whatever is on disk, so callers
    only need to ensure the source artifacts are written first. Returns the
    written ``metrics.json`` path.
    """
    lintfix_dir = escrow.lintfix_dir(project_root)
    plan = _read_json(lintfix_dir / "plan.json")
    optimize = _read_json(lintfix_dir / "optimize.json")
    replay = _read_json(lintfix_dir / "replay.json")

    payload: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sources": {
            "plan": plan is not None,
            "optimize": optimize is not None,
            "replay": replay is not None,
        },
    }
    if plan is not None:
        payload["plan"] = _summarize_plan(plan)
    if optimize is not None:
        payload["optimize"] = _summarize_optimize(optimize)
    if replay is not None:
        payload["replay"] = _summarize_replay(replay)

    out_path = _write_metrics(project_root, payload)
    _print_summary(payload, relpath(project_root, out_path))
    return out_path


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _summarize_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    candidates = _mapping_list(plan.get("candidates"))
    rules_by_class: dict[str, list[str]] = defaultdict(list)
    outside_samples: list[int] = []
    lines_samples: list[int] = []
    for c in candidates:
        klass = str(c.get("classification") or "")
        rules_by_class[klass].append(str(c.get("rule") or ""))
        outside_samples.append(_int_or_zero(c.get("changed_lines_outside_diff")))
        lines_samples.append(_int_or_zero(c.get("changed_lines_total")))
    return {
        "base": plan.get("base"),
        "head": plan.get("head"),
        "candidates_total": len(candidates),
        "by_classification": {k: len(v) for k, v in rules_by_class.items()},
        "auto_rules": sorted(rules_by_class["auto"]),
        "escrow_rules": sorted(rules_by_class["escrow"]),
        "advisory_rules": sorted(rules_by_class["advisory"]),
        "skipped_rules": sorted(rules_by_class["skip"]),
        "avg_outside_diff_lines": _mean(outside_samples),
        "p95_outside_diff_lines": round(quantile(outside_samples, 0.95)),
        "avg_changed_lines": _mean(lines_samples),
    }


def _summarize_optimize(opt: Mapping[str, Any]) -> dict[str, Any]:
    selected = _mapping_list(opt.get("selected"))
    not_selected = _mapping_list(opt.get("not_selected"))
    reason_counts: Counter[str] = Counter(
        str(c.get("reason") or "") for c in not_selected if c.get("reason")
    )
    return {
        "budget": opt.get("budget"),
        "selected": len(selected),
        "selected_rules": sorted(str(c.get("rule") or "") for c in selected),
        "rejected": len(not_selected),
        "total_value": opt.get("total_value", 0),
        "total_cost": opt.get("total_cost", {}),
        "rejection_reasons": dict(reason_counts.most_common()),
    }


def _summarize_replay(replay: Mapping[str, Any]) -> dict[str, Any]:
    rules = _mapping_list(replay.get("rules"))
    by_rec: Counter[str] = Counter(str(r.get("recommended_mode") or "") for r in rules)
    pareto = [str(r.get("rule") or "") for r in rules if r.get("on_pareto_frontier")]
    return {
        "n_replayed": replay.get("n_replayed", 0),
        "n_with_error": replay.get("n_with_error", 0),
        "rules_total": len(rules),
        "by_recommendation": dict(by_rec),
        "pareto_frontier": sorted(pareto),
    }


def _mean(samples: list[int]) -> float:
    if not samples:
        return 0.0
    return round(sum(samples) / len(samples), 2)


def _mapping_list(raw: object) -> list[Mapping[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _int_or_zero(raw: object) -> int:
    if raw is None or isinstance(raw, bool):
        return 0
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw) if math.isfinite(raw) else 0
    if isinstance(raw, str):
        try:
            return int(raw)
        except ValueError:
            return 0
    return 0


def _write_metrics(project_root: Path, payload: dict[str, Any]) -> Path:
    target = escrow.lintfix_dir(project_root) / "metrics.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _print_summary(payload: dict[str, Any], rel_path: str) -> None:
    if ui.is_json():
        return
    ui.gate_row(
        "fix metrics",
        rel_path,
        "ok",
        detail=_sources_detail(payload),
        state="ok",
    )
    ui.section("fix metrics")
    pairs: list[tuple[str, str]] = [("output", rel_path)]
    plan = payload.get("plan")
    if plan:
        by = plan["by_classification"]
        pairs.extend([
            ("candidates", str(plan["candidates_total"])),
            (
                "by class",
                f"auto={by.get('auto', 0)}  escrow={by.get('escrow', 0)}  "
                f"advisory={by.get('advisory', 0)}  skip={by.get('skip', 0)}",
            ),
            ("avg outside-diff", str(plan["avg_outside_diff_lines"])),
            ("p95 outside-diff", str(plan["p95_outside_diff_lines"])),
        ])
        if plan["skipped_rules"]:
            pairs.append(("skipped rules", ", ".join(plan["skipped_rules"])))
    opt = payload.get("optimize")
    if opt:
        pairs.extend([
            ("optimizer", f"selected={opt['selected']}  rejected={opt['rejected']}"),
            ("total value", str(opt.get("total_value", 0))),
        ])
    replay = payload.get("replay")
    if replay:
        pairs.append(("replay rules", str(replay["rules_total"])))
        by_rec = replay.get("by_recommendation", {})
        if by_rec:
            rec = "  ".join(f"{k}={v}" for k, v in sorted(by_rec.items()))
            pairs.append(("recommendations", rec))
    ui.kv_block(pairs)


def _sources_detail(payload: dict[str, Any]) -> str:
    sources = payload.get("sources")
    if not isinstance(sources, Mapping):
        return "sources=none"
    enabled = [str(name) for name, present in sources.items() if present]
    if len(enabled) == len(sources) and enabled:
        return "sources=all"
    return "sources=" + (",".join(enabled) if enabled else "none")


def _fix_metrics_payload(project_root: Path, out_path: Path) -> dict[str, object]:
    metrics = _read_json(out_path) or {}
    return {
        "command": "fix metrics",
        "passed": True,
        "metrics_path": relpath(project_root, out_path),
        "sources": metrics.get("sources", {}),
        "metrics": metrics,
    }
