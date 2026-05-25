"""Property tests for trust score aggregation."""

from __future__ import annotations

from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from interlocks.config import InterlockConfig
from interlocks.metrics import CrapRow, MutationSummary
from interlocks.tasks.stats import _compute_trust


def _cfg(
    *,
    coverage_min: int = 80,
    mutation_min_score: float = 80.0,
    crap_max: float = 30.0,
) -> InterlockConfig:
    return InterlockConfig(
        project_root=Path(),
        src_dir=Path(),
        test_dir=Path(),
        test_runner="pytest",
        test_invoker="python",
        coverage_min=coverage_min,
        mutation_min_score=mutation_min_score,
        crap_max=crap_max,
    )


def _row(crap: float) -> CrapRow:
    return CrapRow("pkg/mod.py", "fn", 1, 10, 10, 10, 0.5, crap)


def _mutation(score: float) -> MutationSummary:
    return MutationSummary(killed=0, survived=0, timeout=0, score=score)


@given(
    crap_values=st.lists(
        st.floats(min_value=0, max_value=1_000, allow_nan=False),
        max_size=20,
    ),
    mutation_score=st.one_of(st.none(), st.floats(min_value=0, max_value=100, allow_nan=False)),
    coverage_pct=st.one_of(st.none(), st.floats(min_value=0, max_value=100, allow_nan=False)),
    suspicious_count=st.integers(min_value=0, max_value=100),
)
def test_trust_score_stays_in_unit_percent_range(
    crap_values: list[float],
    mutation_score: float | None,
    coverage_pct: float | None,
    suspicious_count: int,
) -> None:
    score = _compute_trust(
        crap_rows=[_row(value) for value in crap_values],
        mutation=None if mutation_score is None else _mutation(mutation_score),
        coverage_pct=coverage_pct,
        suspicious_count=suspicious_count,
        cfg=_cfg(),
    )

    assert 0.0 <= score <= 100.0


@given(
    base_count=st.integers(min_value=0, max_value=50),
    extra=st.integers(min_value=0, max_value=50),
)
def test_more_suspicious_tests_never_improve_trust(base_count: int, extra: int) -> None:
    base = _compute_trust(
        crap_rows=[],
        mutation=None,
        coverage_pct=None,
        suspicious_count=base_count,
        cfg=_cfg(),
    )
    worse = _compute_trust(
        crap_rows=[],
        mutation=None,
        coverage_pct=None,
        suspicious_count=base_count + extra,
        cfg=_cfg(),
    )

    assert worse <= base


@given(
    lower=st.floats(min_value=0, max_value=100, allow_nan=False),
    upper=st.floats(min_value=0, max_value=100, allow_nan=False),
)
def test_higher_coverage_never_reduces_trust(lower: float, upper: float) -> None:
    low, high = sorted((lower, upper))

    low_score = _compute_trust(
        crap_rows=[],
        mutation=None,
        coverage_pct=low,
        suspicious_count=0,
        cfg=_cfg(),
    )
    high_score = _compute_trust(
        crap_rows=[],
        mutation=None,
        coverage_pct=high,
        suspicious_count=0,
        cfg=_cfg(),
    )

    assert high_score >= low_score


@given(
    lower=st.floats(min_value=0, max_value=100, allow_nan=False),
    upper=st.floats(min_value=0, max_value=100, allow_nan=False),
)
def test_higher_mutation_score_never_reduces_trust(lower: float, upper: float) -> None:
    low, high = sorted((lower, upper))

    low_score = _compute_trust(
        crap_rows=[],
        mutation=_mutation(low),
        coverage_pct=None,
        suspicious_count=0,
        cfg=_cfg(),
    )
    high_score = _compute_trust(
        crap_rows=[],
        mutation=_mutation(high),
        coverage_pct=None,
        suspicious_count=0,
        cfg=_cfg(),
    )

    assert high_score >= low_score


@given(floor=st.floats(min_value=0, max_value=100, allow_nan=False))
def test_missing_mutation_scores_like_zero_when_floor_is_configured(floor: float) -> None:
    cfg = _cfg(mutation_min_score=floor)

    missing = _compute_trust(
        crap_rows=[],
        mutation=None,
        coverage_pct=None,
        suspicious_count=0,
        cfg=cfg,
    )
    zero = _compute_trust(
        crap_rows=[],
        mutation=_mutation(0.0),
        coverage_pct=None,
        suspicious_count=0,
        cfg=cfg,
    )

    assert missing == zero
