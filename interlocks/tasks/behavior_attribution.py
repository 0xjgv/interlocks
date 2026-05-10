"""Runtime behavior-attribution gate."""

from __future__ import annotations

import sys

from interlocks import run_summary, ui
from interlocks.acceptance_status import (
    AcceptanceStatus,
    classify_acceptance_with_details,
    feature_files,
    remediation_message,
)
from interlocks.acceptance_trace import load_trace_evidence
from interlocks.behavior_attribution import (
    AttributionResult,
    evidence_is_fresh,
    evidence_path,
    format_attribution_failure,
    load_evidence,
    validate_attribution,
)
from interlocks.behavior_coverage import behavior_registry_for_config, parse_scenario_behaviors
from interlocks.config import InterlockConfig, load_config
from interlocks.detect import detect_acceptance_runner
from interlocks.runner import fail, fail_skip, run
from interlocks.tasks.acceptance import task_acceptance_with_attribution

_LABEL = "attribution"
_COMMAND = "behavior-attribution"


def _skip(detail: str) -> None:
    ui.row(_LABEL, _COMMAND, "skipped", detail=detail, state="warn")


def _validate_current_project(cfg: InterlockConfig) -> AttributionResult | None:
    registry = behavior_registry_for_config(cfg)
    if not any(behavior.public_symbol for behavior in registry.behaviors):
        return None
    features = feature_files(cfg.features_dir)
    evidence = load_evidence(evidence_path(cfg))
    trace = load_trace_evidence(cfg.project_root)
    aggregate = trace.reached_symbols if trace is not None else ()
    return validate_attribution(
        registry,
        parse_scenario_behaviors(features),
        evidence,
        aggregate_reached_symbols=aggregate,
    )


def _refresh_evidence_if_needed(cfg: InterlockConfig) -> None:
    if evidence_is_fresh(cfg, evidence_path(cfg)):
        return

    classification = classify_acceptance_with_details(cfg)
    if classification.is_required_failure:
        fail_skip(
            remediation_message(
                classification.status,
                classification.features_dir,
                classification.behavior_result,
            )
        )
    if classification.status is not AcceptanceStatus.RUNNABLE:
        _skip("acceptance is not runnable; no evidence to refresh")
        return
    if detect_acceptance_runner(cfg) == "behave":
        _skip("runtime attribution supports pytest-bdd only")
        return

    acceptance = task_acceptance_with_attribution(cfg)
    if acceptance is None:
        _skip("acceptance task unavailable")
        return
    run(acceptance)


def cmd_behavior_attribution(*, refresh: bool = True) -> None:
    """Verify scenario behavior claims against runtime reach evidence."""
    cfg = load_config()
    if refresh:
        _refresh_evidence_if_needed(cfg)
    result = _validate_current_project(cfg)
    if result is None:
        _skip("no public symbols declared")
        return
    _record_coverage(result)
    if result.is_complete and not result.has_warnings:
        if _below_min_coverage(cfg, result):
            _fail_below_floor(cfg, result)
        ui.row(_LABEL, _COMMAND, "ok", state="ok")
        return

    state = "fail" if cfg.enforce_behavior_attribution and not result.is_complete else "warn"
    status = "failed" if state == "fail" else "warn"
    ui.row(_LABEL, _COMMAND, status, state=state)
    print(format_attribution_failure(result))
    if state == "fail":
        sys.exit(1)
    if _below_min_coverage(cfg, result):
        _fail_below_floor(cfg, result)


def cmd_behavior_attribution_cached_advisory() -> None:
    """Fast advisory mirror used by `interlocks check`."""
    cfg = load_config()
    if not evidence_is_fresh(cfg, evidence_path(cfg)):
        _skip("no fresh evidence — run `interlocks behavior-attribution`")
        return
    result = _validate_current_project(cfg)
    if result is None:
        _skip("no public symbols declared")
        return
    _record_coverage(result)
    if result.is_complete and not result.has_warnings:
        if _below_min_coverage(cfg, result):
            _fail_below_floor(cfg, result)
        ui.row(_LABEL, _COMMAND, "ok", state="ok")
        return
    state = "fail" if cfg.enforce_behavior_attribution and not result.is_complete else "warn"
    status = "failed" if state == "fail" else "warn"
    detail = None if state == "fail" else "cached advisory"
    ui.row(_LABEL, _COMMAND, status, detail=detail, state=state)
    print(format_attribution_failure(result))
    if state == "fail":
        sys.exit(1)
    if _below_min_coverage(cfg, result):
        _fail_below_floor(cfg, result)


def _record_coverage(result: AttributionResult) -> None:
    if result.total_count > 0:
        run_summary.record_attribution_coverage(result.coverage_pct)


def _below_min_coverage(cfg: InterlockConfig, result: AttributionResult) -> bool:
    floor = cfg.attribution_min_coverage
    return floor > 0 and result.total_count > 0 and result.coverage_pct < floor


def _fail_below_floor(cfg: InterlockConfig, result: AttributionResult) -> None:
    floor = cfg.attribution_min_coverage
    fail(
        f"Attribution coverage {result.coverage_pct:.1%} below floor {floor:.1%} "
        f"({result.resolved_count}/{result.total_count} claimed behaviors resolved)"
    )
    sys.exit(1)
