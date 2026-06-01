"""Budgeted multi-rule fix selection — the self-sufficient unblock command (Phase 4).

Usage::

    interlocks fix-optimize                       # plan + optimize, no mutation
    interlocks unblock                            # alias — the engineer-facing verb
    interlocks fix-optimize --budget=renovation
    interlocks fix-optimize --apply               # apply selected, verify, restore on fail
    interlocks fix-optimize --annotate --metrics  # also emit CI annotations + metrics.json
    interlocks fix-optimize --no-stats            # skip auto-discovered replay.json

Discovers fixable rules on the changed file set, classifies each candidate,
then runs the multi-dimensional Pareto-pruned optimizer in
:mod:`lintfix.optimize` to pick the highest-value subset that fits the
selected budget. One run leaves the complete ``.lintfix/`` artifact set:
``plan.json`` + ``optimize.json`` always, ``metrics.json`` with ``--metrics``.
``--stats=`` is auto-discovered from ``.lintfix/replay.json`` when present.
``--apply`` snapshots, applies the selected rules sequentially, runs the
verifier, and restores the tree on any failure.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from interlocks import ui
from interlocks.config import load_config, relpath
from interlocks.lintfix import budgets, escrow, verify
from interlocks.lintfix import optimize as optimize_mod
from interlocks.lintfix import plan as plan_module
from interlocks.lintfix import stats as stats_module
from interlocks.runner import arg_flag_value, arg_value, dump_and_exit
from interlocks.tasks import fix_annotate
from interlocks.tasks.fix_cli import verify_cmd_from_argv
from interlocks.tasks.fix_metrics import aggregate_metrics

if TYPE_CHECKING:
    from pathlib import Path

_DEFAULT_STATS_PATH = ".lintfix/replay.json"


@dataclass(frozen=True)
class _Options:
    """Resolved invocation options — CLI flags merged with keyword overrides."""

    base: str
    budget_name: str
    apply: bool
    stats_path: str
    verify_cmd: tuple[str, ...]
    annotate: bool
    metrics: bool


@dataclass(frozen=True)
class _OptimizeArtifacts:
    plan: plan_module.Plan
    selection: optimize_mod.Selection
    plan_by_rule: dict[str, plan_module.PlannedCandidate]
    optimize_path: Path
    stats_source: str | None


@dataclass(frozen=True)
class _OptionalOutputs:
    annotation_result: fix_annotate.AnnotationResult | None
    metrics_path: Path | None


def cmd_fix_optimize(
    *,
    base: str | None = None,
    budget: str | None = None,
    apply: bool | None = None,
    stats_path: str | None = None,
    verify_cmd: tuple[str, ...] | None = None,
) -> None:
    """Build a fix plan, optimize selection, write artifacts, optionally apply + verify."""
    should_emit_json = _standalone_json_requested()
    opts = _resolve_options(base, budget, apply, stats_path, verify_cmd)
    cfg = load_config()
    plan = plan_module.build_plan(base=opts.base, budget_name=opts.budget_name)

    _exit_if_discovery_failed(opts, plan, should_emit_json)
    artifacts = _build_artifacts(cfg.project_root, opts, plan)
    _print_summary(
        plan,
        artifacts.selection,
        opts,
        cfg.relpath(artifacts.optimize_path),
        artifacts.stats_source,
    )
    outputs = _run_optional_outputs(cfg.project_root, opts, should_emit_json)
    _apply_and_emit_json(cfg.project_root, opts, artifacts, outputs, should_emit_json)


def _exit_if_discovery_failed(
    opts: _Options,
    plan: plan_module.Plan,
    should_emit_json: bool,
) -> None:
    if plan.discovery_error is None:
        return
    if should_emit_json:
        ui.print_json(_fix_optimize_error_payload(opts, plan.discovery_error))
        sys.exit(plan.discovery_error.returncode)
    ui.row(
        "fix-optimize",
        "discover",
        "ruff failed",
        detail=f"rc={plan.discovery_error.returncode}",
        state="fail",
    )
    dump_and_exit(plan.discovery_error.returncode, "", plan.discovery_error.stderr)


def _build_artifacts(
    project_root: Path,
    opts: _Options,
    plan: plan_module.Plan,
) -> _OptimizeArtifacts:
    stats_map = _load_stats(opts.stats_path, project_root)
    stats_source = opts.stats_path if stats_map is not None else None
    candidates = optimize_mod.candidates_from_plan(plan.candidates, stats_map)
    profile = budgets.profile(opts.budget_name, author_cost=plan.author_cost)
    selection = optimize_mod.optimize(candidates, profile)

    plan_by_rule = {c.classification.rule: c for c in plan.candidates}
    patch_paths = plan_module.materialize_escrow_patches(project_root, plan)

    # `plan.json` here is byte-identical to what `fix-plan` writes — one writer.
    plan_module.write_plan_json(project_root, plan_module.serialize(plan, patch_paths=patch_paths))
    payload = _serialize(plan, selection, patch_paths, plan_by_rule)
    out_path = _write_optimize_json(project_root, payload)
    return _OptimizeArtifacts(plan, selection, plan_by_rule, out_path, stats_source)


def _run_optional_outputs(
    project_root: Path,
    opts: _Options,
    should_emit_json: bool,
) -> _OptionalOutputs:
    """Run annotation/metrics outputs before apply so failed applies still report hints."""
    annotation_result: fix_annotate.AnnotationResult | None = None
    if opts.annotate:
        annotation_result = _annotate(project_root, emit_json=should_emit_json)
    metrics_path: Path | None = None
    if opts.metrics:
        metrics_path = aggregate_metrics(project_root)
    return _OptionalOutputs(annotation_result, metrics_path)


def _apply_and_emit_json(
    project_root: Path,
    opts: _Options,
    artifacts: _OptimizeArtifacts,
    outputs: _OptionalOutputs,
    should_emit_json: bool,
) -> None:
    apply_exit_code: int | None = None
    try:
        if opts.apply:
            _apply_selection(
                project_root,
                artifacts.plan_by_rule,
                artifacts.selection,
                opts.verify_cmd,
            )
    except SystemExit as exc:
        apply_exit_code = _system_exit_code(exc)
        if should_emit_json:
            _emit_json_payload(project_root, opts, artifacts, outputs, apply_exit_code)
        raise
    if should_emit_json:
        _emit_json_payload(project_root, opts, artifacts, outputs, apply_exit_code)


def _emit_json_payload(
    project_root: Path,
    opts: _Options,
    artifacts: _OptimizeArtifacts,
    outputs: _OptionalOutputs,
    apply_exit_code: int | None,
) -> None:
    ui.print_json(_fix_optimize_payload(project_root, opts, artifacts, outputs, apply_exit_code))


def _standalone_json_requested() -> bool:
    if not ui.is_json():
        return False
    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            return arg in {"fix-optimize", "unblock"}
    return False


def _resolve_options(
    base: str | None,
    budget: str | None,
    apply: bool | None,
    stats_path: str | None,
    verify_cmd: tuple[str, ...] | None,
) -> _Options:
    """Merge keyword overrides with CLI argv into a resolved :class:`_Options`."""
    cli_budget = arg_value("--mutation-budget=", arg_value("--budget=", "unblock"))
    if arg_flag_value("--renovate", "1") is not None:
        cli_budget = "renovation"
    return _Options(
        base=base if base is not None else arg_value("--base=", "origin/main"),
        budget_name=budget if budget is not None else cli_budget,
        apply=apply if apply is not None else (arg_flag_value("--apply", "1") is not None),
        stats_path=stats_path if stats_path is not None else _resolve_stats_path(),
        verify_cmd=verify_cmd if verify_cmd is not None else verify_cmd_from_argv("fix-optimize"),
        annotate=arg_flag_value("--annotate", "1") is not None,
        metrics=arg_flag_value("--metrics", "1") is not None,
    )


def _resolve_stats_path() -> str:
    """Resolve the replay-stats path: explicit ``--stats=`` > auto-discovery > ``--no-stats``."""
    explicit = arg_value("--stats=", "")
    if explicit:
        return explicit
    if arg_flag_value("--no-stats", "1") is not None:
        return ""
    return _DEFAULT_STATS_PATH


def _annotate(project_root: Path, *, emit_json: bool) -> fix_annotate.AnnotationResult | None:
    """Emit GitHub annotations from ``optimize.json`` — advisory, never alters exit code.

    SPEC §821: annotation errors must not fail ``fix-optimize``. Both a hard
    ``sys.exit`` from the annotator and any other exception are downgraded to a
    warning row here.
    """
    try:
        return fix_annotate.emit_annotations(
            project_root,
            source="optimize",
            emit_json=emit_json,
        )
    except SystemExit as exc:
        ui.row("fix-optimize", "annotate", f"skipped (exit {exc.code})", state="warn")
    except Exception as exc:
        ui.row("fix-optimize", "annotate", str(exc), state="warn")
    return None


def _fix_optimize_payload(
    project_root: Path,
    opts: _Options,
    artifacts: _OptimizeArtifacts,
    outputs: _OptionalOutputs,
    apply_exit_code: int | None,
) -> dict[str, object]:
    """Return the compact JSON summary; full detail stays in .lintfix artifacts."""
    plan = artifacts.plan
    selection = artifacts.selection
    payload: dict[str, object] = {
        "command": "fix-optimize",
        "passed": apply_exit_code in (None, 0),
        "status": _fix_optimize_status(opts, selection, apply_exit_code),
        "plan_path": ".lintfix/plan.json",
        "optimize_path": relpath(project_root, artifacts.optimize_path),
        "base": plan.base,
        "head": plan.head,
        "budget": selection.budget_name,
        "candidate_count": len(plan.candidates),
        "selected_count": len(selection.selected),
        "not_selected_count": len(selection.rejected),
        "selected_rules": _selected_rules(selection),
        "total_value": selection.total_value,
        "total_cost": asdict(selection.total_cost),
        "stats_source": artifacts.stats_source,
        "apply": _apply_payload(selection, opts.apply, apply_exit_code),
    }
    if outputs.annotation_result is not None:
        payload["annotations"] = _annotation_payload(project_root, outputs.annotation_result)
    if outputs.metrics_path is not None:
        payload["metrics_path"] = relpath(project_root, outputs.metrics_path)
    return payload


def _fix_optimize_status(
    opts: _Options,
    selection: optimize_mod.Selection,
    apply_exit_code: int | None,
) -> str:
    if apply_exit_code not in (None, 0):
        return "apply-failed"
    if not opts.apply:
        return "planned"
    if not selection.selected:
        return "nothing-to-apply"
    return "applied"


def _apply_payload(
    selection: optimize_mod.Selection,
    requested: bool,
    exit_code: int | None,
) -> dict[str, object]:
    rules = _selected_rules(selection)
    if not requested:
        return {"requested": False, "status": "not-requested"}
    payload: dict[str, object] = {
        "requested": True,
        "status": "applied" if rules else "nothing-to-apply",
        "selected_rules": rules,
    }
    if exit_code not in (None, 0):
        payload["status"] = "failed"
        payload["returncode"] = exit_code
        payload["failed_patch"] = ".lintfix/failed.patch"
    return payload


def _selected_rules(selection: optimize_mod.Selection) -> list[str]:
    return [selected.candidate.rule for selected in selection.selected]


def _annotation_payload(
    project_root: Path,
    result: fix_annotate.AnnotationResult,
) -> dict[str, object]:
    return {
        "source": result.source,
        "path": relpath(project_root, result.path),
        "found": result.found,
        "notice": result.notice,
        "warning": result.warning,
        "skip": result.skip,
        "annotation_count": result.annotation_count,
    }


def _fix_optimize_error_payload(
    opts: _Options,
    error: plan_module.DiscoveryError,
) -> dict[str, object]:
    return {
        "command": "fix-optimize",
        "passed": False,
        "status": "discovery-failed",
        "base": opts.base,
        "budget": opts.budget_name,
        "error": "ruff discovery failed",
        "returncode": error.returncode,
        "stderr_excerpt": _stderr_excerpt(error.stderr, limit=800),
    }


def _system_exit_code(exc: SystemExit) -> int:
    return exc.code if isinstance(exc.code, int) else 1


def _stderr_excerpt(stderr: str, *, limit: int) -> str:
    cleaned = stderr.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _apply_selection(
    project_root: Path,
    plan_by_rule: dict[str, plan_module.PlannedCandidate],
    selection: optimize_mod.Selection,
    verify_cmd: tuple[str, ...],
) -> None:
    if not selection.selected:
        ui.row("fix-optimize", "(nothing to apply)", "ok", state="ok")
        return
    candidates = _selected_candidates(plan_by_rule, selection)
    result = _apply_candidates(candidates, verify_cmd)
    if result.applied:
        _report_applied(result)
        return
    _write_failed_patch_if_any(project_root, plan_by_rule, candidates)
    _fail_apply(result)


def _selected_candidates(
    plan_by_rule: dict[str, plan_module.PlannedCandidate],
    selection: optimize_mod.Selection,
) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    return tuple(
        (
            plan_by_rule[s.candidate.rule].kind,
            s.candidate.rule,
            plan_by_rule[s.candidate.rule].classification.metrics.files_touched,
        )
        for s in selection.selected
    )


def _apply_candidates(
    candidates: tuple[tuple[str, str, tuple[str, ...]], ...],
    verify_cmd: tuple[str, ...],
) -> verify.BatchVerifyResult:
    if all(kind == "lint" for kind, _, _ in candidates):
        # `rules_and_files` is the lint-only apply path's argument shape; the
        # mixed-candidate path below consumes `candidates` directly.
        rules_and_files = tuple((rule, files) for _, rule, files in candidates)
        return verify.apply_many_with_verify(
            rules_and_files=rules_and_files,
            verify_cmd=verify_cmd,
        )
    return verify.apply_many_candidates_with_verify(
        candidates=candidates,
        verify_cmd=verify_cmd,
    )


def _report_applied(result: verify.BatchVerifyResult) -> None:
    rules = ", ".join(result.applied_rules)
    ui.row("fix-optimize", rules or "(none)", "applied + verified", state="ok")


def _write_failed_patch_if_any(
    project_root: Path,
    plan_by_rule: dict[str, plan_module.PlannedCandidate],
    candidates: tuple[tuple[str, str, tuple[str, ...]], ...],
) -> None:
    failed_patches = "\n".join(
        plan_by_rule[rule].diff_text
        for _, rule, _ in candidates
        if plan_by_rule[rule].diff_text.strip()
    )
    if failed_patches:
        escrow.write_failed_patch(project_root, failed_patches)


def _fail_apply(result: verify.BatchVerifyResult) -> None:
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
        "author_cost": plan.author_cost,
        "active_budget": asdict(
            budgets.profile(selection.budget_name, author_cost=plan.author_cost)
        ),
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
        "kind": c.kind,
        "unsafe": c.unsafe,
        "files": list(c.files),
        "patch_path": patch_paths.get(c.rule),
        "reason": reason,
        "diagnostic_count": planned.diagnostic_count if planned else 0,
    }


def _print_summary(
    plan: plan_module.Plan,
    selection: optimize_mod.Selection,
    opts: _Options,
    out_rel: str,
    stats_source: str | None = None,
) -> None:
    # Suppressed under `--json`: when `fix-optimize` runs inside a `--json` stage
    # (e.g. `check`'s budgeted mutation) this human summary would pollute stdout.
    if ui.is_json():
        return
    stats_pairs = [("stats", stats_source)] if stats_source is not None else []
    ui.section(f"fix-optimize ({opts.base}, budget={opts.budget_name})")
    if not plan.candidates:
        ui.row("fix-optimize", "(no candidates)", "ok", state="ok")
        return

    ui.gate_row("fix-optimize", f"plan written → {out_rel}", "ok", state="ok")
    # `ui.kv_block` is ungated, so the rich SELECTED / NOT SELECTED / plan
    # blocks below need an explicit verbose guard or they leak into default-mode
    # stdout alongside the one-line gate row.
    if not ui.is_verbose():
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
        ("author cost", str(plan.author_cost)),
        ("selected", str(len(selection.selected))),
        ("total value", str(selection.total_value)),
        (
            "total cost",
            f"outside={selection.total_cost.outside_diff}  "
            f"lines={selection.total_cost.changed_lines}  "
            f"files={selection.total_cost.files}  "
            f"risk={selection.total_cost.risk}",
        ),
        *stats_pairs,
    ])


def _candidate_line(c: optimize_mod.Candidate) -> str:
    return (
        f"kind={c.kind}  "
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
