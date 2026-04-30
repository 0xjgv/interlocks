"""Pure runtime behavior-attribution validation helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from interlocks.acceptance_status import feature_files
from interlocks.metrics import iter_py_files, newer_than

if TYPE_CHECKING:
    from collections.abc import Iterable

    from interlocks.behavior_coverage import Behavior, BehaviorRegistry, ScenarioBehavior
    from interlocks.config import InterlockConfig

_DEFAULT_EVIDENCE_PATH = Path(".interlocks/behavior-attribution.json")


@dataclass(frozen=True, order=True)
class ScenarioReach:
    feature_path: Path
    scenario_line: int
    reached_symbols: frozenset[str]


@dataclass(frozen=True)
class AttributionEvidence:
    scenarios: tuple[ScenarioReach, ...]
    created_at: float
    failure: str | None = None


@dataclass(frozen=True, order=True)
class AttributionClaimFailure:
    scenario: ScenarioBehavior
    public_symbol: str


@dataclass(frozen=True)
class AttributionResult:
    mis_attributed: tuple[AttributionClaimFailure, ...] = ()
    unresolved_behaviors: tuple[Behavior, ...] = ()
    instrumentation_gaps: tuple[AttributionClaimFailure, ...] = ()
    informational_symbol_less: tuple[Behavior, ...] = ()
    aggregate_reached_symbols: tuple[str, ...] = ()
    evidence_failure: str | None = None

    @property
    def is_complete(self) -> bool:
        return not (self.mis_attributed or self.unresolved_behaviors)

    @property
    def has_warnings(self) -> bool:
        return bool(self.instrumentation_gaps or self.evidence_failure)


def evidence_path(cfg: InterlockConfig) -> Path:
    return cfg.project_root / _DEFAULT_EVIDENCE_PATH


def load_evidence(path: Path) -> AttributionEvidence | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    created_at = raw.get("created_at")
    scenarios = raw.get("scenarios")
    if not isinstance(created_at, int | float) or not isinstance(scenarios, list):
        return None

    parsed: list[ScenarioReach] = []
    for item in scenarios:
        reach = _parse_reach(item)
        if reach is not None:
            parsed.append(reach)
    failure = raw.get("failure")
    return AttributionEvidence(
        scenarios=tuple(sorted(parsed)),
        created_at=float(created_at),
        failure=failure if isinstance(failure, str) else None,
    )


def write_evidence(
    path: Path,
    *,
    reached_by_scenario: dict[tuple[Path, int], set[str]],
    created_at: float,
    failure: str | None = None,
) -> None:
    payload = {
        "created_at": created_at,
        "failure": failure,
        "scenarios": [
            {
                "feature_path": str(feature_path),
                "scenario_line": scenario_line,
                "reached_symbols": sorted(symbols),
            }
            for (feature_path, scenario_line), symbols in sorted(reached_by_scenario.items())
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def evidence_is_fresh(cfg: InterlockConfig, path: Path | None = None) -> bool:
    target = evidence_path(cfg) if path is None else path
    try:
        evidence_mtime = target.stat().st_mtime
    except OSError:
        return False
    return not any(
        newer_than(input_path, evidence_mtime) for input_path in _attribution_inputs(cfg)
    )


def validate_attribution(
    registry: BehaviorRegistry,
    scenarios: Iterable[ScenarioBehavior],
    evidence: AttributionEvidence | None,
    *,
    aggregate_reached_symbols: tuple[str, ...] = (),
) -> AttributionResult:
    behaviors_by_id = {behavior.behavior_id: behavior for behavior in registry.behaviors}
    public_behaviors = tuple(
        behavior for behavior in registry.behaviors if behavior.public_symbol is not None
    )
    symbol_less = tuple(
        behavior for behavior in registry.behaviors if behavior.public_symbol is None
    )
    classified = _classify_claims(behaviors_by_id, scenarios, evidence)
    return AttributionResult(
        mis_attributed=tuple(sorted(classified[0])),
        unresolved_behaviors=_unresolved_behaviors(public_behaviors, classified[2], classified[3]),
        instrumentation_gaps=tuple(sorted(classified[1])),
        informational_symbol_less=tuple(sorted(symbol_less)),
        aggregate_reached_symbols=tuple(sorted(set(aggregate_reached_symbols))),
        evidence_failure=evidence.failure if evidence is not None else None,
    )


def _classify_claims(
    behaviors_by_id: dict[str, Behavior],
    scenarios: Iterable[ScenarioBehavior],
    evidence: AttributionEvidence | None,
) -> tuple[list[AttributionClaimFailure], list[AttributionClaimFailure], set[str], set[str]]:
    reach_by_key = {
        _scenario_key(reach.feature_path, reach.scenario_line): reach
        for reach in (evidence.scenarios if evidence is not None else ())
    }
    attributed_ids: set[str] = set()
    claimed_public_ids: set[str] = set()
    mis_attributed: list[AttributionClaimFailure] = []
    gaps: list[AttributionClaimFailure] = []
    for scenario in sorted(scenarios):
        behavior = behaviors_by_id.get(scenario.behavior_id)
        if behavior is None or behavior.public_symbol is None:
            continue
        claimed_public_ids.add(behavior.behavior_id)
        claim = AttributionClaimFailure(scenario, behavior.public_symbol)
        reach = reach_by_key.get(_scenario_key(scenario.feature_path, scenario.scenario_line))
        if reach is None:
            gaps.append(claim)
        elif behavior.public_symbol in reach.reached_symbols:
            attributed_ids.add(behavior.behavior_id)
        else:
            mis_attributed.append(claim)
    return mis_attributed, gaps, claimed_public_ids, attributed_ids


def _unresolved_behaviors(
    public_behaviors: tuple[Behavior, ...],
    claimed_public_ids: set[str],
    attributed_ids: set[str],
) -> tuple[Behavior, ...]:
    return tuple(
        behavior
        for behavior in public_behaviors
        if behavior.behavior_id in claimed_public_ids
        and behavior.behavior_id not in attributed_ids
    )


def format_attribution_failure(result: AttributionResult) -> str:
    lines = ["behavior-attribution: scenario claims do not match runtime evidence"]
    if result.evidence_failure:
        lines.append(f"  evidence failure: {result.evidence_failure}")
    _append_claim_failures(lines, "mis-attributed", result.mis_attributed)
    _append_unresolved(lines, result.unresolved_behaviors)
    _append_claim_failures(
        lines,
        "instrumentation gaps",
        result.instrumentation_gaps,
        suffix=" — no per-scenario evidence recorded",
    )
    if result.aggregate_reached_symbols:
        lines.append(
            "  aggregate trace fallback: "
            + ", ".join(result.aggregate_reached_symbols)
            + " (diagnostic only; does not satisfy attribution)"
        )
    if result.informational_symbol_less:
        lines.append("  informational symbol-less behaviors:")
        for behavior in result.informational_symbol_less:
            lines.append(f"    - {behavior.behavior_id} — {behavior.summary}")
    return "\n".join(lines)


def _append_claim_failures(
    lines: list[str],
    heading: str,
    failures: tuple[AttributionClaimFailure, ...],
    *,
    suffix: str | None = None,
) -> None:
    if not failures:
        return
    lines.append(f"  {heading}:")
    for failure in failures:
        detail = suffix or (
            f" claimed {failure.scenario.behavior_id} but did not reach {failure.public_symbol}"
        )
        lines.append(
            "    - "
            f"{failure.scenario.feature_path}:{failure.scenario.scenario_line} "
            f'"{failure.scenario.scenario_title}"{detail}'
        )


def _append_unresolved(lines: list[str], behaviors: tuple[Behavior, ...]) -> None:
    if not behaviors:
        return
    lines.append("  unresolved behavior symbols:")
    for behavior in behaviors:
        lines.append(
            f"    - {behavior.behavior_id} — {behavior.summary} — "
            f"declared {behavior.public_symbol} but no claiming scenario reached it"
        )


def _parse_reach(raw: object) -> ScenarioReach | None:
    if not isinstance(raw, dict):
        return None
    feature_path = raw.get("feature_path")
    scenario_line = raw.get("scenario_line")
    reached_symbols = raw.get("reached_symbols")
    if not isinstance(feature_path, str):
        return None
    if not isinstance(scenario_line, int) or isinstance(scenario_line, bool):
        return None
    if not isinstance(reached_symbols, list):
        return None
    symbols = frozenset(symbol for symbol in reached_symbols if isinstance(symbol, str))
    return ScenarioReach(Path(feature_path), scenario_line, symbols)


def _scenario_key(feature_path: Path, scenario_line: int) -> tuple[Path, int]:
    return (feature_path.resolve(), scenario_line)


def _attribution_inputs(cfg: InterlockConfig) -> tuple[Path, ...]:
    inputs: list[Path] = []
    inputs.extend(feature_files(cfg.features_dir))
    if cfg.features_dir is not None:
        step_defs = cfg.features_dir.parent / "step_defs"
        if step_defs.is_dir():
            inputs.extend(sorted(iter_py_files(step_defs)))
    inputs.append(cfg.project_root / "pyproject.toml")
    return tuple(inputs)
