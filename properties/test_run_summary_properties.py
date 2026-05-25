"""Property tests for run-summary accumulation and loading."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, cast

from hypothesis import given
from hypothesis import strategies as st

from interlocks import run_summary

if TYPE_CHECKING:
    from interlocks.config import InterlockConfig

_FINITE_FLOAT = st.floats(allow_nan=False, allow_infinity=False, width=32)
_CONTEXT = st.text(max_size=40)


@dataclass(frozen=True)
class _Cfg:
    project_root: Path


@given(
    coverage=_FINITE_FLOAT,
    mutation=_FINITE_FLOAT,
    crap=_FINITE_FLOAT,
    attribution=_FINITE_FLOAT,
    lint_count=st.integers(min_value=0, max_value=1_000_000),
    context=_CONTEXT,
)
def test_run_summary_flush_load_round_trips_generated_measurements(
    coverage: float,
    mutation: float,
    crap: float,
    attribution: float,
    lint_count: int,
    context: str,
) -> None:
    with TemporaryDirectory() as raw_root:
        cfg = cast("InterlockConfig", _Cfg(Path(raw_root)))
        run_summary.reset()
        run_summary.record_coverage(coverage)
        run_summary.record_mutation(mutation)
        run_summary.record_crap_max(crap)
        run_summary.record_attribution_coverage(attribution)
        run_summary.record_lint_count(lint_count)
        run_summary.record_context(context)

        run_summary.flush(cfg)
        loaded = run_summary.load(cfg)

    run_summary.reset()
    assert loaded is not None
    assert loaded.coverage_pct == float(coverage)
    assert loaded.mutation_score == float(mutation)
    assert loaded.crap_max_observed == float(crap)
    assert loaded.attribution_coverage == float(attribution)
    assert loaded.lint_violations == lint_count
    assert loaded.context == context
    assert loaded.created_at is not None


@given(
    existing=_FINITE_FLOAT,
    raw_pct=st.one_of(
        _FINITE_FLOAT,
        st.booleans(),
        st.none(),
        st.text(max_size=20),
        st.sampled_from((float("nan"), float("inf"), float("-inf"))),
    ),
)
def test_run_summary_coverage_sidecar_accepts_only_finite_numeric_percent(
    existing: float,
    raw_pct: object,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        cfg = cast("InterlockConfig", _Cfg(root))
        interlocks_dir = root / ".interlocks"
        interlocks_dir.mkdir()
        (interlocks_dir / "coverage.json").write_text(
            json.dumps({"totals": {"percent_covered": raw_pct}}),
            encoding="utf-8",
        )
        run_summary.reset()
        run_summary.record_coverage(existing)
        run_summary.flush(cfg)
        loaded = run_summary.load(cfg)

    run_summary.reset()
    assert loaded is not None
    if (
        isinstance(raw_pct, (int, float))
        and not isinstance(raw_pct, bool)
        and math.isfinite(raw_pct)
    ):
        assert loaded.coverage_pct == float(raw_pct)
    else:
        assert loaded.coverage_pct == float(existing)
