"""Shared acceptance / Gherkin readiness classifier.

Used by stages, the acceptance task, and `interlocks evaluate` so feature and
scenario counting does not drift between callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from interlocks.behavior_coverage import (
    BehaviorCoverageValidationResult,
    behavior_coverage_for_config,
    count_feature_scenarios,
    format_behavior_coverage_failure,
)
from interlocks.runner import Task

if TYPE_CHECKING:
    from collections.abc import Iterable

    from interlocks.config import InterlockConfig


class AcceptanceStatus(StrEnum):
    DISABLED = "disabled"
    OPTIONAL_MISSING = "optional_missing"
    MISSING_FEATURES_DIR = "missing_features_dir"
    MISSING_FEATURE_FILES = "missing_feature_files"
    MISSING_SCENARIOS = "missing_scenarios"
    MISSING_BEHAVIOR_COVERAGE = "missing_behavior_coverage"
    RUNNABLE = "runnable"


@dataclass(frozen=True)
class AcceptanceClassification:
    status: AcceptanceStatus
    features_dir: Path | None
    behavior_result: BehaviorCoverageValidationResult | None = None

    @property
    def is_required_failure(self) -> bool:
        return self.status in _REQUIRED_FAILURE_STATUSES


_REQUIRED_FAILURE_STATUSES = frozenset({
    AcceptanceStatus.MISSING_FEATURES_DIR,
    AcceptanceStatus.MISSING_FEATURE_FILES,
    AcceptanceStatus.MISSING_SCENARIOS,
    AcceptanceStatus.MISSING_BEHAVIOR_COVERAGE,
})


def feature_files(features_dir: Path | None) -> list[Path]:
    if features_dir is None or not features_dir.is_dir():
        return []
    return sorted(features_dir.rglob("*.feature"))


def count_scenarios(files: Iterable[Path]) -> int:
    return sum(count_feature_scenarios(path) for path in files)


def classify_acceptance(cfg: InterlockConfig) -> AcceptanceStatus:
    return classify_acceptance_with_details(cfg).status


def classify_acceptance_with_details(cfg: InterlockConfig) -> AcceptanceClassification:
    features_dir = cfg.features_dir
    if cfg.acceptance_runner == "off":
        return AcceptanceClassification(AcceptanceStatus.DISABLED, features_dir)
    required = cfg.require_acceptance

    def missing(required_status: AcceptanceStatus) -> AcceptanceClassification:
        status = required_status if required else AcceptanceStatus.OPTIONAL_MISSING
        return AcceptanceClassification(status, features_dir)

    if features_dir is None or not features_dir.is_dir():
        return missing(AcceptanceStatus.MISSING_FEATURES_DIR)
    files = feature_files(features_dir)
    if not files:
        return missing(AcceptanceStatus.MISSING_FEATURE_FILES)
    if count_scenarios(files) == 0:
        return missing(AcceptanceStatus.MISSING_SCENARIOS)
    if required:
        behavior_result = behavior_coverage_for_config(cfg, files)
        if not behavior_result.is_complete:
            return AcceptanceClassification(
                AcceptanceStatus.MISSING_BEHAVIOR_COVERAGE, features_dir, behavior_result
            )
    return AcceptanceClassification(AcceptanceStatus.RUNNABLE, features_dir)


def remediation_message(
    status: AcceptanceStatus,
    features_dir: Path | None,
    behavior_result: BehaviorCoverageValidationResult | None = None,
) -> str:
    """Actionable message reused by acceptance command + stage enforcement."""
    scaffold_hint = "run `interlocks init-acceptance` to scaffold one"
    match status:
        case AcceptanceStatus.MISSING_FEATURES_DIR:
            return f"acceptance: features directory not found — {scaffold_hint}"
        case AcceptanceStatus.MISSING_FEATURE_FILES:
            target = features_dir if features_dir is not None else Path("tests/features")
            return f"acceptance: no `.feature` files under {target} — {scaffold_hint}"
        case AcceptanceStatus.MISSING_SCENARIOS:
            return (
                "acceptance: feature files exist but contain no `Scenario`"
                " — add at least one scenario"
            )
        case AcceptanceStatus.MISSING_BEHAVIOR_COVERAGE:
            if behavior_result is None:
                return (
                    "acceptance: behavior coverage incomplete"
                    " — add or update Gherkin behavior markers"
                )
            return format_behavior_coverage_failure(behavior_result)
        case _:
            return ""


def required_acceptance_failure_task(
    status: AcceptanceStatus,
    features_dir: Path | None,
    behavior_result: BehaviorCoverageValidationResult | None = None,
) -> Task:
    return acceptance_failure_task(AcceptanceClassification(status, features_dir, behavior_result))


def acceptance_failure_task(classification: AcceptanceClassification) -> Task:
    """Synthetic Task that surfaces a required-acceptance failure inside `run_tasks`."""
    message = remediation_message(
        classification.status, classification.features_dir, classification.behavior_result
    )
    payload = f"import sys; sys.stderr.write({message!r} + chr(10)); sys.exit(1)"
    return Task(
        description="Acceptance (required)",
        cmd=["python", "-c", payload],
    )
