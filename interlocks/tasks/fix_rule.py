"""Rule-scoped fix support command.

Usage::

    interlocks fix-rule --rule=I001            # plan only (no mutation)
    interlocks fix-rule --rule=I001 --apply    # apply iff auto + budget pass + verify pass
    interlocks fix-rule --rule=F401            # writes .lintfix/escrow/F401.patch

Defaults are non-mutating. ``F401`` and other escrow-mode rules never mutate
the tree even with ``--apply`` — they always materialize a patch for review.
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from interlocks import ui
from interlocks.config import load_config, relpath
from interlocks.lintfix import budgets, classify, diff, escrow, rules, simulate, verify
from interlocks.runner import arg_flag_value, arg_value
from interlocks.tasks.fix_cli import verify_cmd_from_argv

if TYPE_CHECKING:
    from interlocks.config import InterlockConfig

_ESCROW_MODES: tuple[str, ...] = ("escrow", "advisory")


@dataclass(frozen=True)
class _FixRuleArgs:
    """Resolved fix-rule inputs — CLI kwargs with argv fallbacks applied."""

    rule: str
    apply: bool
    base: str
    budget_name: str
    verify_cmd: tuple[str, ...]


def _resolve_args(
    rule: str | None,
    apply: bool | None,
    base: str | None,
    budget: str | None,
    verify_cmd: tuple[str, ...] | None,
) -> _FixRuleArgs:
    """Fold each ``None`` kwarg back to its argv-derived default."""
    return _FixRuleArgs(
        rule=rule if rule is not None else _required_rule(),
        apply=apply if apply is not None else (arg_flag_value("--apply", "1") is not None),
        base=base if base is not None else arg_value("--base=", "origin/main"),
        budget_name=budget if budget is not None else arg_value("--budget=", "unblock"),
        verify_cmd=verify_cmd if verify_cmd is not None else verify_cmd_from_argv("fix-rule"),
    )


def cmd_fix_rule(
    *,
    rule: str | None = None,
    apply: bool | None = None,
    base: str | None = None,
    budget: str | None = None,
    verify_cmd: tuple[str, ...] | None = None,
) -> None:
    """Plan (or apply) a rule-scoped ruff fix. Falls back to argv when args omitted."""
    args = _resolve_args(rule, apply, base, budget, verify_cmd)

    cfg = load_config()
    base_sha = diff.resolve_base(args.base)
    if not base_sha:
        if ui.is_json():
            ui.print_json(_fix_rule_base_payload(args))
            return
        ui.row(
            "fix-rule",
            args.rule,
            "skipped",
            detail=f"unknown base ref {args.base!r}",
            state="warn",
        )
        return

    files = diff.changed_files(base_sha)
    if not files:
        if ui.is_json():
            ui.print_json(_fix_rule_no_files_payload(args))
            return
        ui.row("fix-rule", args.rule, "no changed .py files vs base", state="ok")
        return

    candidate = simulate.simulate_rule(args.rule, files)
    if candidate.returncode >= 2:
        if ui.is_json():
            ui.print_json(_fix_rule_ruff_failure_payload(args, candidate))
            sys.exit(candidate.returncode)
        ui.row(
            "fix-rule",
            args.rule,
            "ruff failed",
            detail=f"rc={candidate.returncode}",
            state="fail",
        )
        sys.exit(candidate.returncode)

    hunks = diff.changed_hunks(base_sha, files)
    policy = rules.policy_for(args.rule)
    profile = budgets.profile(args.budget_name)
    classification = classify.classify(
        patch_text=candidate.diff,
        diff_hunks=hunks,
        policy=policy,
        budget=profile,
    )

    _print_plan(classification, candidate.diff, args.base, args.budget_name)

    rc = _dispatch_classification(classification, args, candidate, files, cfg)
    if ui.is_json():
        ui.print_json(_fix_rule_payload(cfg, args, classification, files, rc))
    if rc:
        sys.exit(rc)


def _dispatch_classification(
    classification: classify.Classification,
    args: _FixRuleArgs,
    candidate: simulate.CandidatePatch,
    files: tuple[str, ...],
    cfg: InterlockConfig,
) -> int:
    """Act on the classified candidate; return a non-zero exit code on failure.

    Covers the four post-classify workflows — skip, escrow/advisory, plan-only
    (no ``--apply``), and auto-apply + verify — keeping ``cmd_fix_rule`` a thin
    orchestrator.
    """
    rule = args.rule
    if classification.mode == "skip":
        ui.row("fix-rule", rule, "skip", detail=classification.reason or "", state="warn")
        return 0

    if classification.mode in _ESCROW_MODES:
        target = escrow.write_patch(cfg.project_root, rule, candidate.diff)
        ui.row("fix-rule", rule, classification.mode, detail=cfg.relpath(target), state="ok")
        return 0

    if not args.apply:
        ui.row("fix-rule", rule, "auto-eligible", detail="re-run with --apply", state="ok")
        return 0

    files_to_apply = classification.metrics.files_touched or files
    result = verify.apply_with_verify(rule=rule, files=files_to_apply, verify_cmd=args.verify_cmd)
    if result.applied:
        ui.row("fix-rule", rule, "applied + verified", state="ok")
        return 0

    escrow.write_failed_patch(cfg.project_root, candidate.diff)
    ui.row(
        "fix-rule",
        rule,
        "verify failed; tree restored",
        detail=".lintfix/failed.patch",
        state="fail",
    )
    return result.returncode or 1


def _print_plan(c: classify.Classification, diff_text: str, base: str, budget_name: str) -> None:
    if ui.is_json():
        return
    m = c.metrics
    ui.section(f"fix-rule plan ({base}, budget={budget_name})")
    rows: list[tuple[str, str]] = [
        ("rule", c.rule),
        ("mode", c.mode),
        ("files", str(len(m.files_touched))),
        ("changed lines", str(m.changed_lines_total)),
        ("inside diff", str(m.changed_lines_inside_diff)),
        ("outside diff", str(m.changed_lines_outside_diff)),
        ("risk", str(c.cost.risk)),
    ]
    if c.reason:
        rows.append(("reason", c.reason))
    ui.kv_block(rows)
    if diff_text.strip() and ui.is_verbose():
        ui.section("candidate patch")
        print(diff_text)


def _fix_rule_base_payload(args: _FixRuleArgs) -> dict[str, object]:
    return {
        "command": "fix-rule",
        "passed": True,
        "status": "unknown-base",
        "rule": args.rule,
        "base": args.base,
        "budget": args.budget_name,
        "apply_requested": args.apply,
        "error": f"unknown base ref {args.base!r}",
    }


def _fix_rule_no_files_payload(args: _FixRuleArgs) -> dict[str, object]:
    return {
        "command": "fix-rule",
        "passed": True,
        "status": "no-changed-files",
        "rule": args.rule,
        "base": args.base,
        "budget": args.budget_name,
        "apply_requested": args.apply,
    }


def _fix_rule_ruff_failure_payload(
    args: _FixRuleArgs,
    candidate: simulate.CandidatePatch,
) -> dict[str, object]:
    return {
        "command": "fix-rule",
        "passed": False,
        "status": "ruff-failed",
        "rule": args.rule,
        "base": args.base,
        "budget": args.budget_name,
        "apply_requested": args.apply,
        "returncode": candidate.returncode,
    }


def _fix_rule_payload(
    cfg: InterlockConfig,
    args: _FixRuleArgs,
    classification: classify.Classification,
    files: tuple[str, ...],
    returncode: int,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "command": "fix-rule",
        "passed": returncode == 0,
        "status": _fix_rule_status(classification, args, returncode),
        "rule": args.rule,
        "base": args.base,
        "budget": args.budget_name,
        "apply_requested": args.apply,
        "mode": classification.mode,
        "reason": classification.reason,
        "changed_files": list(files),
        "candidate_files": list(files),
        "metrics": asdict(classification.metrics),
        "cost": asdict(classification.cost),
    }
    _add_fix_rule_artifact_paths(payload, cfg, classification, returncode)
    return payload


def _fix_rule_status(
    classification: classify.Classification,
    args: _FixRuleArgs,
    returncode: int,
) -> str:
    if returncode:
        return "apply-failed"
    if classification.mode in _ESCROW_MODES:
        return classification.mode
    if classification.mode == "skip":
        return "skip"
    return "applied" if args.apply else "auto-eligible"


def _add_fix_rule_artifact_paths(
    payload: dict[str, object],
    cfg: InterlockConfig,
    classification: classify.Classification,
    returncode: int,
) -> None:
    if classification.mode in _ESCROW_MODES:
        patch_path = escrow.escrow_dir(cfg.project_root) / f"{classification.rule}.patch"
        payload["patch_path"] = relpath(cfg.project_root, patch_path)
    if returncode:
        payload["failed_patch"] = ".lintfix/failed.patch"


def _required_rule() -> str:
    value = arg_value("--rule=", "")
    if len(value) == 0:
        if ui.is_json():
            ui.print_json({
                "command": "fix-rule",
                "passed": False,
                "status": "missing-rule",
                "error": "missing required --rule=<value>",
                "usage": "usage: interlocks fix-rule --rule=<value> [--apply] [--json]",
            })
            sys.exit(2)
        print("interlocks fix-rule: missing required --rule=<value>", file=sys.stderr)
        sys.exit(2)
    return value
