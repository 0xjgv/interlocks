"""Per-stage measured-value summary written to ``.interlocks/run-summary.json``.

Tasks record what they measured (coverage %, mutation score, max CRAP, attribution
coverage) into a process-local accumulator. Stages call :func:`flush` at the end
to persist a single JSON file the agent — and ``interlocks baseline advance`` —
can read back.

Thin layer: no validation beyond type coercion. The baseline ratchet is the
consumer; everything else (CLI, gates) ignores this file.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from interlocks.config import coerce_float

if TYPE_CHECKING:
    from interlocks.config import InterlockConfig

_DEFAULT_PATH = Path(".interlocks/run-summary.json")
_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RunSummary:
    """One stage's measured values. Any field may be ``None`` if not recorded."""

    coverage_pct: float | None = None
    mutation_score: float | None = None
    crap_max_observed: float | None = None
    attribution_coverage: float | None = None
    context: str | None = None
    created_at: float | None = None


_state: RunSummary = RunSummary()


def reset() -> None:
    """Drop accumulated measurements (called at the top of each stage)."""
    global _state  # noqa: PLW0603  (module singleton accumulator)
    _state = RunSummary()


def record_coverage(pct: float) -> None:
    global _state  # noqa: PLW0603  (module singleton accumulator)
    _state = replace(_state, coverage_pct=float(pct))


def record_mutation(score: float) -> None:
    global _state  # noqa: PLW0603  (module singleton accumulator)
    _state = replace(_state, mutation_score=float(score))


def record_crap_max(crap: float) -> None:
    global _state  # noqa: PLW0603  (module singleton accumulator)
    _state = replace(_state, crap_max_observed=float(crap))


def record_attribution_coverage(coverage: float) -> None:
    global _state  # noqa: PLW0603  (module singleton accumulator)
    _state = replace(_state, attribution_coverage=float(coverage))


def record_context(context: str) -> None:
    global _state  # noqa: PLW0603  (module singleton accumulator)
    _state = replace(_state, context=context)


def current() -> RunSummary:
    """Return the in-memory accumulator (read-only view)."""
    return _state


def summary_path(cfg: InterlockConfig) -> Path:
    return cfg.project_root / _DEFAULT_PATH


def flush(cfg: InterlockConfig) -> Path:
    """Persist the accumulator to ``.interlocks/run-summary.json``.

    Always writes (even when nothing was recorded) so the file's mtime tracks
    the most recent stage. Pulls the coverage % from
    ``.interlocks/coverage.json`` when present (coverage runs as a subprocess,
    so it can't call :func:`record_coverage` directly). Returns the written
    path.
    """
    _maybe_pull_coverage(cfg)
    snapshot = replace(_state, created_at=time.time())
    payload: dict[str, Any] = {"schema_version": _SCHEMA_VERSION, **asdict(snapshot)}
    target = summary_path(cfg)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _maybe_pull_coverage(cfg: InterlockConfig) -> None:
    """Read ``coverage.json`` (coverage.py >= 5.0 schema) into the accumulator.

    Schema: ``{"totals": {"percent_covered": <0..100 float>, ...}, ...}``.
    Silently no-op when the file is absent or unparseable — coverage may have
    been skipped or coverage.py may not have completed.
    """
    coverage_json = cfg.project_root / ".interlocks" / "coverage.json"
    try:
        raw = json.loads(coverage_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    totals = raw.get("totals") if isinstance(raw, dict) else None
    if not isinstance(totals, dict):
        return
    pct = totals.get("percent_covered")
    if isinstance(pct, (int, float)) and not isinstance(pct, bool):
        record_coverage(float(pct))


def load(cfg: InterlockConfig) -> RunSummary | None:
    """Read ``.interlocks/run-summary.json`` back into a :class:`RunSummary`.

    Returns ``None`` when the file is missing or unparseable.
    """
    target = summary_path(cfg)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    return RunSummary(
        coverage_pct=coerce_float(raw.get("coverage_pct")),
        mutation_score=coerce_float(raw.get("mutation_score")),
        crap_max_observed=coerce_float(raw.get("crap_max_observed")),
        attribution_coverage=coerce_float(raw.get("attribution_coverage")),
        context=raw.get("context") if isinstance(raw.get("context"), str) else None,
        created_at=coerce_float(raw.get("created_at")),
    )
