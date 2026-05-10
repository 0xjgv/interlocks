"""Project quality floor: load/save/advance ``.interlocks/baseline.json``.

The progressive preset elevates the resolved threshold for each metric to the
floor recorded here. ``il baseline advance`` reads the latest run summary and
writes a new floor only when measurements are strictly better.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from interlocks.config import coerce_float

if TYPE_CHECKING:
    from interlocks.config import InterlockConfig
    from interlocks.run_summary import RunSummary

_DEFAULT_PATH = Path(".interlocks/baseline.json")
SCHEMA_VERSION = 1

# (field_name, higher_is_stricter). Drives merge / strictly-better / regression checks.
METRICS: tuple[tuple[str, bool], ...] = (
    ("coverage_min", True),
    ("mutation_min_score", True),
    ("attribution_min_coverage", True),
    ("crap_max", False),
)


@dataclass(frozen=True, slots=True)
class BaselineFloor:
    coverage_min: float | None = None
    mutation_min_score: float | None = None
    crap_max: float | None = None
    attribution_min_coverage: float | None = None
    updated_at: str | None = None
    advanced_from_sha: str | None = None

    @property
    def is_empty(self) -> bool:
        return (
            self.coverage_min is None
            and self.mutation_min_score is None
            and self.crap_max is None
            and self.attribution_min_coverage is None
        )


def baseline_path(cfg: InterlockConfig) -> Path:
    return cfg.project_root / _DEFAULT_PATH


def load_baseline(cfg: InterlockConfig) -> BaselineFloor:
    """Return the recorded floor, or an empty :class:`BaselineFloor` if missing.

    Permissive: malformed JSON, missing keys, and wrong-type values all fall
    through silently — gates never block on a corrupted baseline file.
    """
    target = baseline_path(cfg)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return BaselineFloor()
    if not isinstance(raw, dict):
        return BaselineFloor()
    floors_raw = raw.get("floors")
    floors: dict[str, object] = floors_raw if isinstance(floors_raw, dict) else {}
    updated_raw = raw.get("updated_at")
    sha_raw = raw.get("advanced_from_sha")
    return BaselineFloor(
        coverage_min=coerce_float(floors.get("coverage_min")),
        mutation_min_score=coerce_float(floors.get("mutation_min_score")),
        crap_max=coerce_float(floors.get("crap_max")),
        attribution_min_coverage=coerce_float(floors.get("attribution_min_coverage")),
        updated_at=updated_raw if isinstance(updated_raw, str) else None,
        advanced_from_sha=sha_raw if isinstance(sha_raw, str) else None,
    )


def write_baseline(cfg: InterlockConfig, floor: BaselineFloor) -> Path:
    """Persist ``floor`` to ``.interlocks/baseline.json``. Returns the written path."""
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": floor.updated_at or utc_now_iso(),
        "advanced_from_sha": floor.advanced_from_sha,
        "floors": {
            "coverage_min": floor.coverage_min,
            "mutation_min_score": floor.mutation_min_score,
            "crap_max": floor.crap_max,
            "attribution_min_coverage": floor.attribution_min_coverage,
        },
    }
    target = baseline_path(cfg)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return target


def merge_higher(a: BaselineFloor, b: BaselineFloor) -> BaselineFloor:
    """Per-metric pick of the stricter floor; metadata from ``b`` falling back to ``a``."""
    merged: dict[str, Any] = {
        field: _pick_stricter(getattr(a, field), getattr(b, field), higher_better)
        for field, higher_better in METRICS
    }
    merged["updated_at"] = b.updated_at or a.updated_at
    merged["advanced_from_sha"] = b.advanced_from_sha or a.advanced_from_sha
    return BaselineFloor(**merged)


def floor_from_summary(summary: RunSummary) -> BaselineFloor:
    """Map a :class:`RunSummary` onto a candidate floor (no metadata)."""
    return BaselineFloor(
        coverage_min=summary.coverage_pct,
        mutation_min_score=summary.mutation_score,
        crap_max=summary.crap_max_observed,
        attribution_min_coverage=summary.attribution_coverage,
    )


def is_strictly_better(candidate: BaselineFloor, current_floor: BaselineFloor) -> bool:
    """True when at least one metric improves and none regress vs ``current_floor``."""
    improved = False
    for field, higher_better in METRICS:
        new = getattr(candidate, field)
        old = getattr(current_floor, field)
        if new is None:
            continue
        if old is None:
            improved = True
            continue
        cmp = (new > old) if higher_better else (new < old)
        regressed = (new < old) if higher_better else (new > old)
        if regressed:
            return False
        if cmp:
            improved = True
    return improved


def advance_from_summary(
    cfg: InterlockConfig, summary: RunSummary, *, sha: str | None = None
) -> BaselineFloor | None:
    """Compute a new floor from ``summary``; return it only when strictly better.

    Caller is responsible for persisting the returned floor (separate step so
    the CLI can dry-run with ``--check``).
    """
    candidate = floor_from_summary(summary)
    if candidate.is_empty:
        return None
    current_floor = load_baseline(cfg)
    if not is_strictly_better(candidate, current_floor):
        return None
    merged = merge_higher(current_floor, candidate)
    return replace(merged, updated_at=utc_now_iso(), advanced_from_sha=sha)


def _pick_stricter(a: float | None, b: float | None, higher_better: bool) -> float | None:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b) if higher_better else min(a, b)


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
