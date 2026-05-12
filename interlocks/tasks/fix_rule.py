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

from interlocks import ui
from interlocks.config import load_config
from interlocks.lintfix import budgets, classify, diff, escrow, rules, simulate, verify
from interlocks.runner import arg_flag_value, arg_value

_DEFAULT_VERIFY_CMD: tuple[str, ...] = ("interlocks", "ci")
_ESCROW_MODES: tuple[str, ...] = ("escrow", "advisory")


def cmd_fix_rule(
    *,
    rule: str | None = None,
    apply: bool | None = None,
    base: str | None = None,
    budget: str | None = None,
    verify_cmd: tuple[str, ...] | None = None,
) -> None:
    """Plan (or apply) a rule-scoped ruff fix. Falls back to argv when args omitted."""
    rule = rule or _required_rule()
    apply = apply if apply is not None else (arg_flag_value("--apply", "1") is not None)
    base = base or arg_value("--base=", "origin/main")
    budget_name = budget or arg_value("--budget=", "unblock")
    verify_cmd = verify_cmd or _verify_cmd_argv()

    cfg = load_config()
    base_sha = diff.resolve_base(base)
    if not base_sha:
        ui.row("fix-rule", rule, "skipped", detail=f"unknown base ref {base!r}", state="warn")
        return

    files = diff.changed_files(base_sha)
    if not files:
        ui.row("fix-rule", rule, "no changed .py files vs base", state="ok")
        return

    candidate = simulate.simulate_rule(rule, files)
    if candidate.returncode >= 2:
        ui.row("fix-rule", rule, "ruff failed", detail=f"rc={candidate.returncode}", state="fail")
        sys.exit(candidate.returncode)

    hunks = diff.changed_hunks(base_sha, files)
    policy = rules.policy_for(rule)
    profile = budgets.profile(budget_name)
    classification = classify.classify(
        patch_text=candidate.diff,
        diff_hunks=hunks,
        policy=policy,
        budget=profile,
    )

    _print_plan(classification, candidate.diff, base, budget_name)

    if classification.mode == "skip":
        ui.row("fix-rule", rule, "skip", detail=classification.reason or "", state="warn")
        return

    if classification.mode in _ESCROW_MODES:
        target = escrow.write_patch(cfg.project_root, rule, candidate.diff)
        rel = cfg.relpath(target)
        ui.row("fix-rule", rule, classification.mode, detail=rel, state="ok")
        return

    if not apply:
        ui.row("fix-rule", rule, "auto-eligible", detail="re-run with --apply", state="ok")
        return

    files_to_apply = classification.metrics.files_touched or files
    result = verify.apply_with_verify(rule=rule, files=files_to_apply, verify_cmd=verify_cmd)
    if result.applied:
        ui.row("fix-rule", rule, "applied + verified", state="ok")
        return
    escrow.write_failed_patch(cfg.project_root, candidate.diff)
    ui.row(
        "fix-rule",
        rule,
        "verify failed; tree restored",
        detail=".lintfix/failed.patch",
        state="fail",
    )
    sys.exit(result.returncode or 1)


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
