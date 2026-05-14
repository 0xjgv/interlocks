"""Rule-scoped fix support command.

Usage::

    interlocks fix-rule --rule=I001            # plan only (no mutation)
    interlocks fix-rule --rule=I001 --apply    # apply iff auto + budget pass + verify pass
    interlocks fix-rule --rule=F401            # writes .lintfix/escrow/F401.patch

Defaults are non-mutating. ``F401`` and other escrow-mode rules never mutate
the tree even with ``--apply`` — they always materialize a patch for review.
"""

from __future__ import annotations

import shlex
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from interlocks import ui
from interlocks.config import load_config
from interlocks.lintfix import budgets, classify, diff, escrow, rules, simulate, verify
from interlocks.runner import arg_flag_value, arg_value

if TYPE_CHECKING:
    from interlocks.config import InterlockConfig

_DEFAULT_VERIFY_CMD: tuple[str, ...] = ("interlocks", "ci")
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
        rule=rule or _required_rule(),
        apply=apply if apply is not None else (arg_flag_value("--apply", "1") is not None),
        base=base or arg_value("--base=", "origin/main"),
        budget_name=budget or arg_value("--budget=", "unblock"),
        verify_cmd=verify_cmd or _verify_cmd_argv(),
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
        ui.row("fix-rule", args.rule, "no changed .py files vs base", state="ok")
        return

    candidate = simulate.simulate_rule(args.rule, files)
    if candidate.returncode >= 2:
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


def _required_rule() -> str:
    value = arg_value("--rule=", "")
    if not value:
        print("interlocks fix-rule: missing required --rule=<value>", file=sys.stderr)
        sys.exit(2)
    return value


def _verify_cmd_argv() -> tuple[str, ...]:
    raw = arg_value("--verify-cmd=", "")
    if raw:
        return tuple(shlex.split(raw))
    return _DEFAULT_VERIFY_CMD
