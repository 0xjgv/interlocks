"""Runtime behavior-attribution gate."""

from __future__ import annotations

import sys

from interlocks import ui
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
from interlocks.runner import fail_skip, run
from interlocks.tasks.acceptance import task_acceptance_with_attribution

_LABEL = "attribution"
_COMMAND = "behavior-attribution"


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
        ui.row(
            _LABEL,
            _COMMAND,
            "skipped",
            detail="acceptance is not runnable; no evidence to refresh",
            state="warn",
        )
        return
    if detect_acceptance_runner(cfg) == "behave":
        ui.row(
            _LABEL,
            _COMMAND,
            "skipped",
            detail="runtime attribution supports pytest-bdd only",
            state="warn",
        )
        return

    acceptance = task_acceptance_with_attribution(cfg)
    if acceptance is None:
        ui.row(_LABEL, _COMMAND, "skipped", detail="acceptance task unavailable", state="warn")
        return
    run(acceptance)


def cmd_behavior_attribution(*, refresh: bool = True) -> None:
    """Verify scenario behavior claims against runtime reach evidence."""
    cfg = load_config()
    if refresh:
        _refresh_evidence_if_needed(cfg)
    result = _validate_current_project(cfg)
    if result is None:
        ui.row(_LABEL, _COMMAND, "skipped", detail="no public symbols declared", state="warn")
        return
    if result.is_complete and not result.has_warnings:
        ui.row(_LABEL, _COMMAND, "ok", state="ok")
        return

    enforced = getattr(cfg, "enforce_behavior_attribution", False)
    state = "fail" if enforced and not result.is_complete else "warn"
    status = "failed" if state == "fail" else "warn"
    ui.row(_LABEL, _COMMAND, status, state=state)
    print(format_attribution_failure(result))
    if state == "fail":
        sys.exit(1)


def cmd_behavior_attribution_cached_advisory() -> None:
    """Fast advisory mirror used by `interlocks check`."""
    cfg = load_config()
    path = evidence_path(cfg)
    if not evidence_is_fresh(cfg, path):
        ui.row(
            _LABEL,
            _COMMAND,
            "skipped",
            detail="no fresh evidence — run `interlocks behavior-attribution`",
            state="warn",
        )
        return
    result = _validate_current_project(cfg)
    if result is None:
        ui.row(_LABEL, _COMMAND, "skipped", detail="no public symbols declared", state="warn")
        return
    if result.is_complete and not result.has_warnings:
        ui.row(_LABEL, _COMMAND, "ok", state="ok")
        return
    ui.row(_LABEL, _COMMAND, "warn", detail="cached advisory", state="warn")
    print(format_attribution_failure(result))
