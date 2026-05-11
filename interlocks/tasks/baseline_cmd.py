"""``interlocks baseline`` subcommand handlers.

Actions:
  ``show``     — print the current floor (table or ``--json``).
  ``init``     — capture today's measured values as the initial floor.
  ``advance``  — write a new floor when the latest run summary improves on it.
  ``check``    — exit 1 when measured values are below the floor (used in CI to
                 verify the ratchet held).

All four read ``.interlocks/run-summary.json`` for measurements and
``.interlocks/baseline.json`` for the existing floor.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, replace
from typing import TYPE_CHECKING

from interlocks import ui
from interlocks.baseline import (
    METRICS,
    advance_from_summary,
    baseline_path,
    floor_from_summary,
    load_baseline,
    utc_now_iso,
    write_baseline,
)
from interlocks.config import load_config
from interlocks.run_summary import RunSummary
from interlocks.run_summary import load as load_summary
from interlocks.runner import capture, fail_skip, ok

if TYPE_CHECKING:
    from interlocks.baseline import BaselineFloor
    from interlocks.config import InterlockConfig


def cmd_baseline() -> None:
    """Dispatch ``interlocks baseline <action>``. Defaults to ``show``."""
    args = [a for a in sys.argv[2:] if not a.startswith("-")]
    flags = [a for a in sys.argv[2:] if a.startswith("-")]
    action = args[0] if args else "show"
    json_mode = "--json" in flags
    auto_pr = "--auto-pr" in flags

    cfg = load_config()
    if action == "show":
        _cmd_show(cfg, json_mode=json_mode)
    elif action == "init":
        _cmd_init(cfg, json_mode=json_mode)
    elif action == "advance":
        _cmd_advance(cfg, json_mode=json_mode, auto_pr=auto_pr)
    elif action == "check":
        _cmd_check(cfg, json_mode=json_mode)
    else:
        fail_skip(f"unknown baseline action: {action} (expected show|init|advance|check)")


def _cmd_show(cfg: InterlockConfig, *, json_mode: bool) -> None:
    floor = load_baseline(cfg)
    if json_mode:
        print(json.dumps(_floor_to_dict(cfg, floor), sort_keys=True, indent=2))
        return
    if floor.is_empty:
        print("(no baseline recorded — run `interlocks baseline init`)")
        return
    ui.section("Floor")
    ui.kv_block(_floor_rows(floor))
    if floor.updated_at or floor.advanced_from_sha:
        ui.section("Last advance")
        meta: list[tuple[str, str]] = []
        if floor.updated_at:
            meta.append(("updated_at", floor.updated_at))
        if floor.advanced_from_sha:
            meta.append(("advanced_from_sha", floor.advanced_from_sha))
        ui.kv_block(meta)


def _cmd_init(cfg: InterlockConfig, *, json_mode: bool) -> None:
    summary = _require_summary(cfg)
    candidate = floor_from_summary(summary)
    if candidate.is_empty:
        fail_skip("baseline init: run-summary has no measurements to capture")
    floor = replace(candidate, updated_at=utc_now_iso(), advanced_from_sha=_git_head_sha())
    target = write_baseline(cfg, floor)
    if json_mode:
        print(json.dumps(_floor_to_dict(cfg, floor), sort_keys=True, indent=2))
        return
    if ui.is_verbose():
        ok(f"wrote {cfg.relpath(target)}")
    ui.section("Floor")
    ui.kv_block(_floor_rows(floor))


def _cmd_advance(cfg: InterlockConfig, *, json_mode: bool, auto_pr: bool) -> None:
    summary = _require_summary(cfg)
    sha = _git_head_sha()
    new_floor = advance_from_summary(cfg, summary, sha=sha)
    if new_floor is None:
        if json_mode:
            print(json.dumps({"advanced": False}, sort_keys=True))
            return
        print("no improvement vs current floor — leaving baseline.json unchanged")
        return
    target = write_baseline(cfg, new_floor)
    if json_mode:
        payload = {"advanced": True, "auto_pr": auto_pr, **_floor_to_dict(cfg, new_floor)}
        print(json.dumps(payload, sort_keys=True, indent=2))
        return
    if ui.is_verbose():
        ok(f"updated {cfg.relpath(target)}")
    ui.section("New floor")
    ui.kv_block(_floor_rows(new_floor))
    if auto_pr and ui.is_verbose():
        ui.section("Auto-PR")
        print("  (workflow will open the chore(baseline): … PR)")


def _cmd_check(cfg: InterlockConfig, *, json_mode: bool) -> None:
    floor = load_baseline(cfg)
    summary = _require_summary(cfg)
    candidate = floor_from_summary(summary)
    regressions: list[str] = []
    for field, higher_better in METRICS:
        measured = getattr(candidate, field)
        current_floor = getattr(floor, field)
        if measured is None or current_floor is None:
            continue
        if higher_better and measured < current_floor:
            regressions.append(f"{field}: {measured} below floor {current_floor}")
        if not higher_better and measured > current_floor:
            regressions.append(f"{field}: {measured} above floor {current_floor}")
    if json_mode:
        print(json.dumps({"ok": not regressions, "regressions": regressions}, sort_keys=True))
        if regressions:
            sys.exit(1)
        return
    if not regressions:
        if ui.is_verbose():
            ok("measured values meet or beat the recorded floor")
        return
    for line in regressions:
        print(f"  ✗ {line}")
    sys.exit(1)


def _require_summary(cfg: InterlockConfig) -> RunSummary:
    summary = load_summary(cfg)
    if summary is None:
        fail_skip(
            "baseline: no run summary found at .interlocks/run-summary.json — "
            "run `interlocks check` or `interlocks ci` first"
        )
    return summary


def _floor_to_dict(cfg: InterlockConfig, floor: BaselineFloor) -> dict[str, object]:
    payload = asdict(floor)
    payload["path"] = cfg.relpath(baseline_path(cfg))
    return payload


def _floor_rows(floor: BaselineFloor) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for key, value in (
        ("coverage_min", floor.coverage_min),
        ("mutation_min_score", floor.mutation_min_score),
        ("crap_max", floor.crap_max),
        ("attribution_min_coverage", floor.attribution_min_coverage),
    ):
        if value is not None:
            rows.append((key, _fmt(value)))
    return rows


def _fmt(value: float) -> str:
    rounded = round(value, 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return str(rounded)


def _git_head_sha() -> str | None:
    """Return short HEAD sha, or ``None`` outside a git repo."""
    result = capture(["git", "rev-parse", "--short", "HEAD"])
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None
