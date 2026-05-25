"""Runtime behavior-attribution gate."""

from __future__ import annotations

import sys
import time
from typing import Literal

from interlocks import run_summary, ui
from interlocks.acceptance_status import (
    AcceptanceClassification,
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
from interlocks.runner import (
    Task,
    fail,
    fail_skip,
    reset_results,
    results_snapshot,
    run,
    stage_json,
)
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


def cmd_behavior_attribution(*, refresh: bool = True, emit_json: bool = True) -> None:
    """Verify scenario behavior claims against runtime reach evidence."""
    cfg = load_config()
    if emit_json and ui.is_json():
        _cmd_behavior_attribution_json(cfg, refresh=refresh)
        return
    if refresh:
        _refresh_evidence_if_needed(cfg)
    result = _validate_current_project(cfg)
    if result is None:
        _skip("no public symbols declared")
        return
    _handle_attribution_result(cfg, result, warning_detail=None, force_ok=True)


def _cmd_behavior_attribution_json(cfg: InterlockConfig, *, refresh: bool) -> None:
    if refresh:
        refresh_failure = _refresh_evidence_if_needed_json(cfg)
        if refresh_failure is not None:
            ui.print_json(refresh_failure)
            sys.exit(1)
    result = _validate_current_project(cfg)
    if result is None:
        ui.print_json(_attribution_skip_payload("no public symbols declared"))
        return
    _record_coverage(result)
    payload = _attribution_payload(cfg, result)
    ui.print_json(payload)
    if payload["passed"] is False:
        sys.exit(1)


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
    _handle_attribution_result(cfg, result, warning_detail="cached advisory", force_ok=False)


def _handle_attribution_result(
    cfg: InterlockConfig,
    result: AttributionResult,
    *,
    warning_detail: str | None,
    force_ok: bool,
) -> None:
    _record_coverage(result)
    if result.is_complete and not result.has_warnings:
        _handle_complete_result(cfg, result, force=force_ok)
        return

    state = "fail" if cfg.enforce_behavior_attribution and not result.is_complete else "warn"
    _report_attribution_issue(state, result, warning_detail)
    if state == "fail":
        sys.exit(1)
    if _below_min_coverage(cfg, result):
        _fail_below_floor(cfg, result)


def _refresh_evidence_if_needed_json(cfg: InterlockConfig) -> dict[str, object] | None:
    if evidence_is_fresh(cfg, evidence_path(cfg)):
        return None

    classification = classify_acceptance_with_details(cfg)
    failure = _refresh_classification_failure_payload(classification)
    if failure is not None:
        return failure
    if not _can_refresh_pytest_bdd_evidence(cfg, classification):
        return None

    acceptance = task_acceptance_with_attribution(cfg)
    if acceptance is None:
        return None
    return _run_acceptance_refresh_json(acceptance)


def _run_acceptance_refresh_json(acceptance: Task) -> dict[str, object] | None:
    reset_results()
    start = time.monotonic()
    run(acceptance, no_exit=True)
    elapsed = time.monotonic() - start
    passed = all(gate.status == "ok" for gate in results_snapshot())
    if passed:
        reset_results()
        return None
    payload = stage_json("behavior-attribution", passed=False, elapsed=elapsed)
    payload["status"] = "failed"
    payload["error"] = "acceptance evidence refresh failed"
    return payload


def _refresh_classification_failure_payload(
    classification: AcceptanceClassification,
) -> dict[str, object] | None:
    if not classification.is_required_failure:
        return None
    message = remediation_message(
        classification.status,
        classification.features_dir,
        classification.behavior_result,
    )
    return _attribution_refresh_failure_payload(message)


def _can_refresh_pytest_bdd_evidence(
    cfg: InterlockConfig, classification: AcceptanceClassification
) -> bool:
    return (
        classification.status is AcceptanceStatus.RUNNABLE
        and detect_acceptance_runner(cfg) != "behave"
    )


def _handle_complete_result(
    cfg: InterlockConfig, result: AttributionResult, *, force: bool
) -> None:
    if _below_min_coverage(cfg, result):
        _fail_below_floor(cfg, result)
    ui.row(_LABEL, _COMMAND, "ok", state="ok", force=force)


def _attribution_skip_payload(reason: str) -> dict[str, object]:
    return {
        "command": "behavior-attribution",
        "passed": True,
        "status": "skipped",
        "reason": reason,
        "next_actions": [],
    }


def _attribution_refresh_failure_payload(message: str) -> dict[str, object]:
    return {
        "command": "behavior-attribution",
        "passed": False,
        "status": "failed",
        "error": message,
        "next_actions": ["Run `interlocks init-acceptance` or fix acceptance coverage."],
    }


def _attribution_payload(cfg: InterlockConfig, result: AttributionResult) -> dict[str, object]:
    floor_failure = _below_min_coverage(cfg, result)
    incomplete_failure = cfg.enforce_behavior_attribution and not result.is_complete
    passed = not (floor_failure or incomplete_failure)
    status = _attribution_status(result, passed=passed)
    payload: dict[str, object] = {
        "command": "behavior-attribution",
        "passed": passed,
        "status": status,
        "coverage": _attribution_coverage_payload(result),
        "counts": _attribution_count_payload(result),
        "next_actions": _attribution_next_actions(status, floor_failure=floor_failure),
    }
    if status != "ok":
        payload["detail"] = format_attribution_failure(result)
    if floor_failure:
        payload["error"] = _attribution_floor_message(cfg, result)
    elif incomplete_failure:
        payload["error"] = format_attribution_failure(result)
    return payload


def _attribution_status(result: AttributionResult, *, passed: bool) -> str:
    if not passed:
        return "failed"
    if not result.is_complete or result.has_warnings:
        return "warn"
    return "ok"


def _attribution_coverage_payload(result: AttributionResult) -> dict[str, object]:
    return {
        "resolved": result.resolved_count,
        "total": result.total_count,
        "pct": round(result.coverage_pct * 100, 1),
    }


def _attribution_count_payload(result: AttributionResult) -> dict[str, int]:
    return {
        "mis_attributed": len(result.mis_attributed),
        "unresolved_behaviors": len(result.unresolved_behaviors),
        "instrumentation_gaps": len(result.instrumentation_gaps),
        "informational_symbol_less": len(result.informational_symbol_less),
        "aggregate_reached_symbols": len(result.aggregate_reached_symbols),
    }


def _attribution_next_actions(status: str, *, floor_failure: bool) -> list[str]:
    if floor_failure:
        return [
            "Add scenario coverage for claimed behaviors, then rerun "
            "`interlocks behavior-attribution`."
        ]
    if status == "ok":
        return []
    return [
        "Update behavior markers or scenario code, then rerun `interlocks behavior-attribution`."
    ]


def _attribution_floor_message(cfg: InterlockConfig, result: AttributionResult) -> str:
    floor = cfg.attribution_min_coverage
    return (
        f"Attribution coverage {result.coverage_pct:.1%} below floor {floor:.1%} "
        f"({result.resolved_count}/{result.total_count} claimed behaviors resolved)"
    )


def _report_attribution_issue(
    state: Literal["fail", "warn"],
    result: AttributionResult,
    warning_detail: str | None,
) -> None:
    status = "failed" if state == "fail" else "warn"
    detail = None if state == "fail" else warning_detail
    ui.row(_LABEL, _COMMAND, status, detail=detail, state=state)
    if not ui.is_json():
        print(format_attribution_failure(result))


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
