"""Property tests for mutation-test scoping helpers."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

from hypothesis import given
from hypothesis import strategies as st

from interlocks.metrics import MutationSummary
from interlocks.tasks import mutation

if TYPE_CHECKING:
    from interlocks.config import InterlockConfig

_SEGMENT = st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,10}", fullmatch=True)
_DIR = st.one_of(
    st.just(""),
    st.just("."),
    st.lists(_SEGMENT, min_size=1, max_size=3).map("/".join),
)
_REL_PY = st.lists(_SEGMENT, min_size=1, max_size=4).map(lambda parts: "/".join(parts) + ".py")
_REL_NON_PY = st.lists(_SEGMENT, min_size=1, max_size=4).map(
    lambda parts: "/".join(parts) + ".txt"
)
_PATHS = st.sets(st.one_of(_REL_PY, _REL_NON_PY), max_size=12)
_PERCENT = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)
_NONNEG = st.integers(min_value=0, max_value=10_000)
_SURVIVORS = st.lists(
    st.from_regex(
        r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*__mutmut_\d+",
        fullmatch=True,
    ),
    max_size=30,
)
_TARGET_GLOB = st.from_regex(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\.\*",
    fullmatch=True,
)
_TARGET_GLOBS = st.lists(_TARGET_GLOB, max_size=40)


@dataclass(frozen=True)
class _Cfg:
    mutation_since_ref: str
    src_dir_arg: str
    test_dir_arg: str
    enforce_mutation: bool = False
    mutation_min_score: float = 80.0


def _prefix(directory: str) -> str:
    return "" if directory in ("", ".") else f"{directory}/"


def _expected_globs(changed: set[str], src_dir: str, test_dir: str) -> list[str]:
    src_prefix = _prefix(src_dir)
    test_prefix = _prefix(test_dir)
    expected: list[str] = []
    for path in sorted(changed):
        if not path.endswith(".py"):
            continue
        if test_prefix and path.startswith(test_prefix):
            continue
        if src_prefix and not path.startswith(src_prefix):
            continue
        expected.append(f"{path[:-3].replace('/', '.')}.*")
    return expected


@given(changed=_PATHS, src_dir=_DIR, test_dir=_DIR)
def test_changed_to_globs_maps_only_scoped_python_files(
    changed: set[str], src_dir: str, test_dir: str
) -> None:
    globs = mutation._changed_to_globs(changed, src_dir, test_dir)

    assert globs == _expected_globs(changed, src_dir, test_dir)
    assert globs == sorted(globs)
    assert all(glob.endswith(".*") for glob in globs)


@given(directory=_DIR)
def test_dir_prefix_adds_slash_only_for_non_root_dirs(directory: str) -> None:
    expected = "" if directory in ("", ".") else f"{directory}/"

    assert mutation._dir_prefix(directory) == expected


@given(ref=st.text(max_size=40), src_dir=_DIR, test_dir=_DIR)
def test_resolve_changed_globs_full_run_does_not_read_git(
    ref: str, src_dir: str, test_dir: str
) -> None:
    cfg = _Cfg(ref, src_dir, test_dir)

    with patch.object(
        mutation,
        "changed_py_files_vs",
        side_effect=AssertionError("full mutation run must not inspect changed files"),
    ):
        assert mutation._resolve_changed_globs(
            cast("InterlockConfig", cfg), changed_only=False
        ) == (None, None)


@given(changed=_PATHS, ref=st.text(max_size=40), src_dir=_DIR, test_dir=_DIR)
def test_resolve_changed_globs_incremental_uses_configured_ref_and_scope(
    changed: set[str], ref: str, src_dir: str, test_dir: str
) -> None:
    cfg = _Cfg(ref, src_dir, test_dir)
    seen: list[str] = []

    def fake_changed_py_files_vs(base: str) -> set[str]:
        seen.append(base)
        return changed

    with patch.object(mutation, "changed_py_files_vs", fake_changed_py_files_vs):
        resolved = mutation._resolve_changed_globs(cast("InterlockConfig", cfg), changed_only=True)
        assert resolved == (
            _expected_globs(changed, src_dir, test_dir),
            changed,
        )

    assert seen == [ref]


@given(line=st.text(max_size=80))
def test_is_spinner_line_matches_left_stripped_braille_prefix(line: str) -> None:
    stripped = line.lstrip()
    expected = bool(stripped) and stripped[0] in mutation._BRAILLE_SPINNER

    assert mutation._is_spinner_line(line) is expected


@given(line=st.text(max_size=80))
def test_is_progress_line_matches_mutmut_progress_tokens(line: str) -> None:
    stripped = line.strip()
    expected = "/" in stripped and ("\U0001f389" in stripped or "\U0001fae5" in stripped)

    assert mutation._is_progress_line(line) is expected


@given(done=_NONNEG, total=st.integers(min_value=1, max_value=10_000))
def test_is_progress_line_accepts_mutmut_fraction_with_either_status_token(
    done: int,
    total: int,
) -> None:
    assert mutation._is_progress_line(f"{done}/{total} 🎉 0") is True
    assert mutation._is_progress_line(f"{done}/{total} 🫥 0") is True


@given(line=st.text(max_size=80))
def test_is_keep_line_matches_done_or_rate_lines(line: str) -> None:
    stripped = line.strip().lower()
    expected = "mutations/second" in stripped or stripped.startswith("done")

    assert mutation._is_keep_line(line) is expected


@given(
    done=st.integers(min_value=0, max_value=100_000),
    total=st.integers(min_value=1, max_value=100_000),
)
def test_mutation_progress_label_extracts_mutmut_fraction(done: int, total: int) -> None:
    line = f"⠋ {done}/{total}  🎉 1 🫥 2"

    assert mutation._mutation_progress_label(line) == f"mutmut {done}/{total}"


@given(
    done=st.integers(min_value=0, max_value=100_000),
    total=st.integers(min_value=1, max_value=100_000),
)
def test_mutation_progress_from_line_extracts_fraction(done: int, total: int) -> None:
    line = f"prefix {done}/{total} suffix"

    progress = mutation._mutation_progress_from_line(line)

    assert progress == mutation._MutationProgress(done, total)


@given(label=st.from_regex(r"[A-Za-z][A-Za-z ]{0,39}", fullmatch=True))
def test_mutation_progress_label_normalizes_spinner_text(label: str) -> None:
    raw = f"⠋ Running {label}"
    expected = label.strip().lower() or "mutmut"

    assert mutation._mutation_progress_label(raw) == expected


@given(
    checked=st.integers(min_value=0, max_value=100_000),
    total=st.one_of(st.none(), st.integers(min_value=-10, max_value=100_000)),
)
def test_completion_pct_is_bounded_when_total_is_known(checked: int, total: int | None) -> None:
    pct = mutation._completion_pct(checked, total)

    if total is None or total <= 0:
        assert pct is None
    else:
        assert pct == min(checked / total * 100, 100.0)


@given(checked=st.integers(min_value=0, max_value=100_000))
def test_completion_pct_is_none_without_positive_total(checked: int) -> None:
    assert mutation._completion_pct(checked, None) is None
    assert mutation._completion_pct(checked, 0) is None


@given(
    elapsed=st.floats(min_value=0.0, max_value=10_000.0, allow_nan=False, allow_infinity=False),
    checked=st.integers(min_value=0, max_value=100_000),
    total=st.one_of(st.none(), st.integers(min_value=0, max_value=100_000)),
)
def test_estimated_full_runtime_only_when_more_mutants_remain(
    elapsed: float, checked: int, total: int | None
) -> None:
    estimate = mutation._estimated_full_runtime(elapsed, checked, total)

    if total is None or total <= checked or checked <= 0:
        assert estimate is None
    else:
        assert estimate == elapsed * total / checked


@given(elapsed=st.floats(min_value=0.0, max_value=10_000.0, allow_nan=False, allow_infinity=False))
def test_estimated_full_runtime_is_none_before_first_checked_mutant(elapsed: float) -> None:
    assert mutation._estimated_full_runtime(elapsed, 0, 1) is None


@given(
    checked=st.integers(min_value=0, max_value=100_000),
    total=st.one_of(st.none(), st.integers(min_value=-10, max_value=100_000)),
    elapsed=st.one_of(
        st.none(),
        st.floats(min_value=0.0, max_value=10_000.0, allow_nan=False, allow_infinity=False),
    ),
    completed=st.booleans(),
)
def test_mutation_progress_fields_report_denominator_and_estimate(
    checked: int,
    total: int | None,
    elapsed: float | None,
    completed: bool,
) -> None:
    fields = mutation._mutation_progress_fields(
        checked,
        total,
        elapsed=elapsed,
        completed=completed,
    )

    if total is None:
        assert "total_mutants" not in fields
    else:
        assert fields["total_mutants"] == total
    assert ("completion_pct" in fields) is (total is not None and total > 0)
    expect_estimate = (
        elapsed is not None and not completed and total is not None and total > checked > 0
    )
    assert ("estimated_full_runtime_seconds" in fields) is expect_estimate


@given(
    checked=st.integers(min_value=0, max_value=100_000),
    total=st.integers(min_value=1, max_value=100_000),
)
def test_mutation_progress_completion_is_rounded_percentage(
    checked: int,
    total: int,
) -> None:
    fields = mutation._mutation_progress_fields(checked, total)

    assert fields["completion_pct"] == round(min((checked / total) * 100, 100.0), 3)


@given(
    survivor_count=st.integers(min_value=0, max_value=100),
    visible_count=st.integers(min_value=0, max_value=100),
)
def test_survivor_truncation_field_reports_omitted_count(
    survivor_count: int, visible_count: int
) -> None:
    fields = mutation._survivor_truncation_field(survivor_count, visible_count)
    truncated = survivor_count - visible_count

    if truncated > 0:
        assert fields == {"truncated_survivors": truncated}
    else:
        assert fields == {}


@given(globs=st.one_of(st.none(), _TARGET_GLOBS))
def test_mutation_target_fields_cap_targets_without_losing_count(
    globs: list[str] | None,
) -> None:
    fields = mutation._mutation_target_fields(globs)
    targets = list(globs or [])
    limit = mutation._MUTATION_TARGET_LIMIT

    assert fields["targets"] == targets[:limit]
    assert fields["target_count"] == len(targets)
    if len(targets) > limit:
        assert fields["truncated_targets"] == len(targets) - limit
    else:
        assert "truncated_targets" not in fields


@given(globs=st.lists(_TARGET_GLOB, max_size=mutation._MUTATION_TARGET_LIMIT))
def test_mutation_target_fields_omit_truncation_at_display_limit(globs: list[str]) -> None:
    fields = mutation._mutation_target_fields(globs)

    assert fields["targets"] == globs
    assert fields["target_count"] == len(globs)
    assert "truncated_targets" not in fields


@given(
    score=_PERCENT,
    completed=st.booleans(),
    failed=st.booleans(),
    score_failed=st.booleans(),
)
def test_mutation_result_message_fields_follow_failure_precedence(
    score: float,
    completed: bool,
    failed: bool,
    score_failed: bool,
) -> None:
    summary = MutationSummary(killed=1, survived=1, timeout=0, score=score)
    context = mutation._MutationPayloadContext(
        min_score=60.0,
        completed=completed,
        changed_only=False,
        globs=None,
        changed=None,
        log_path=Path(".interlocks/mutation.log"),
        elapsed=1.0,
        max_runtime=600,
        min_coverage=70.0,
        coverage_pct=90.0,
        total_mutants=None,
    )

    fields = mutation._mutation_result_message_fields(
        summary,
        context,
        failed=failed,
        score_failed=score_failed,
    )

    if failed and not completed:
        assert "timed out" in fields["error"]
    elif score_failed:
        assert fields["error"].startswith("Mutation score")
    elif not completed:
        assert fields == {"warning": "mutation run timed out before all mutants were checked"}
    else:
        assert fields == {}


@given(score=_PERCENT, min_score=_PERCENT)
def test_mutation_result_score_failure_message_names_thresholds(
    score: float,
    min_score: float,
) -> None:
    summary = MutationSummary(killed=1, survived=1, timeout=0, score=score)
    context = mutation._MutationPayloadContext(
        min_score=min_score,
        completed=True,
        changed_only=False,
        globs=None,
        changed=None,
        log_path=Path(".interlocks/mutation.log"),
        elapsed=1.0,
        max_runtime=600,
        min_coverage=70.0,
        coverage_pct=90.0,
        total_mutants=None,
    )

    fields = mutation._mutation_result_message_fields(
        summary,
        context,
        failed=False,
        score_failed=True,
    )

    assert fields == {"error": f"Mutation score {score:.1f}% below threshold {min_score:.1f}%"}


@given(
    cli_score=st.one_of(st.none(), st.floats(allow_nan=False, allow_infinity=False)),
    default=st.one_of(st.none(), st.floats(allow_nan=False, allow_infinity=False)),
    enforce=st.booleans(),
    configured=st.floats(allow_nan=False, allow_infinity=False),
)
def test_resolve_min_score_obeys_cli_default_enforcement_precedence(
    cli_score: float | None,
    default: float | None,
    enforce: bool,
    configured: float,
) -> None:
    argv = ["interlocks", "mutation"]
    if cli_score is not None:
        argv.append(f"--min-score={cli_score}")
    cfg = _Cfg(
        mutation_since_ref="HEAD",
        src_dir_arg="interlocks",
        test_dir_arg="tests",
        enforce_mutation=enforce,
        mutation_min_score=configured,
    )

    with patch.object(sys, "argv", argv):
        resolved = mutation._resolve_min_score(cast("InterlockConfig", cfg), default=default)

    expected = cli_score if cli_score is not None else default
    if expected is None and enforce:
        expected = configured
    assert resolved == expected


@given(configured=st.floats(allow_nan=False, allow_infinity=False))
def test_resolve_min_score_returns_none_when_no_floor_source(configured: float) -> None:
    cfg = _Cfg(
        mutation_since_ref="HEAD",
        src_dir_arg="interlocks",
        test_dir_arg="tests",
        enforce_mutation=False,
        mutation_min_score=configured,
    )

    with patch.object(sys, "argv", ["interlocks", "mutation"]):
        assert mutation._resolve_min_score(cast("InterlockConfig", cfg)) is None


@given(score=_PERCENT, floor=st.one_of(st.none(), _PERCENT), completed=st.booleans())
def test_mutation_status_matches_score_floor_and_completion(
    score: float, floor: float | None, completed: bool
) -> None:
    summary = MutationSummary(killed=1, survived=1, timeout=0, score=score)

    status = mutation._mutation_status(summary, floor, completed=completed)

    if not completed:
        assert status == "partial"
    elif floor is not None and score < floor:
        assert status == "failed"
    else:
        assert status == "ok"


@given(score=_PERCENT, floor=st.one_of(st.none(), _PERCENT), completed=st.booleans())
def test_mutation_failed_requires_floor_and_complete_evidence(
    score: float, floor: float | None, completed: bool
) -> None:
    summary = MutationSummary(killed=1, survived=1, timeout=0, score=score)

    failed = mutation._mutation_failed(summary, floor, completed=completed)

    assert failed is (floor is not None and (not completed or score < floor))


@given(score=_PERCENT, floor=_PERCENT)
def test_mutation_failed_treats_incomplete_enforced_run_as_failure(
    score: float,
    floor: float,
) -> None:
    summary = MutationSummary(killed=1, survived=1, timeout=0, score=score)

    assert mutation._mutation_failed(summary, floor, completed=False) is True


@given(floor=st.one_of(st.none(), _PERCENT), completed=st.booleans())
def test_mutation_no_results_failed_requires_enforced_incomplete_run(
    floor: float | None, completed: bool
) -> None:
    run_config = mutation._MutationRun(
        min_coverage=0.0,
        coverage_pct=100.0,
        timeout=1,
        min_score=floor,
        changed_only=False,
        globs=None,
        changed=None,
    )

    failed = mutation._mutation_no_results_failed(run_config, completed=completed)

    assert failed is (floor is not None and not completed)


@given(reason=st.text(max_size=40), elapsed=_PERCENT, next_action=st.text(max_size=80))
def test_mutation_skip_payload_is_stable(reason: str, elapsed: float, next_action: str) -> None:
    payload = mutation._mutation_skip_payload(
        reason=reason,
        elapsed=elapsed,
        next_action=next_action,
        min_coverage=70.0,
        coverage_pct=85.1234,
    )

    assert payload["command"] == "mutation"
    assert payload["passed"] is True
    assert payload["status"] == "skipped"
    assert payload["elapsed_seconds"] == round(elapsed, 3)
    assert payload["reason"] == reason
    assert payload["next_action"] == next_action
    assert payload["min_coverage"] == 70.0
    assert payload["coverage_pct"] == 85.123


@given(
    min_coverage=st.one_of(st.none(), _PERCENT),
    coverage_pct=st.one_of(st.none(), _PERCENT),
)
def test_mutation_skip_payload_includes_optional_coverage_only_when_present(
    min_coverage: float | None,
    coverage_pct: float | None,
) -> None:
    payload = mutation._mutation_skip_payload(
        reason="generated",
        elapsed=1.25,
        next_action="rerun",
        min_coverage=min_coverage,
        coverage_pct=coverage_pct,
    )

    assert ("min_coverage" in payload) is (min_coverage is not None)
    assert ("coverage_pct" in payload) is (coverage_pct is not None)
    if min_coverage is not None:
        assert payload["min_coverage"] == min_coverage
    if coverage_pct is not None:
        assert payload["coverage_pct"] == round(coverage_pct, 3)


@given(
    killed=_NONNEG,
    survived=_NONNEG,
    timed_out=_NONNEG,
    score=_PERCENT,
    floor=st.one_of(st.none(), _PERCENT),
    completed=st.booleans(),
    changed_only=st.booleans(),
    survivors=_SURVIVORS,
    targets=_TARGET_GLOBS,
)
def test_mutation_payload_counts_and_limits_survivors(
    killed: int,
    survived: int,
    timed_out: int,
    score: float,
    floor: float | None,
    completed: bool,
    changed_only: bool,
    survivors: list[str],
    targets: list[str],
) -> None:
    summary = MutationSummary(
        killed=killed,
        survived=survived,
        timeout=timed_out,
        score=score,
        survivors=survivors,
    )

    payload = mutation._mutation_payload(
        summary,
        mutation._MutationPayloadContext(
            min_score=floor,
            completed=completed,
            changed_only=changed_only,
            globs=targets if changed_only else None,
            changed=None,
            log_path=Path(".interlocks/mutation.log"),
            elapsed=1.23456,
            max_runtime=600,
            min_coverage=70.0,
            coverage_pct=99.9,
            total_mutants=None,
        ),
    )

    assert payload["command"] == "mutation"
    expected_failed = floor is not None and (not completed or score < floor)
    assert payload["passed"] is not expected_failed
    assert payload["status"] == mutation._mutation_status(summary, floor, completed=completed)
    assert payload["checked_mutants"] == killed + survived + timed_out
    assert payload["score"] == round(score, 3)
    assert payload["killed"] == killed
    assert payload["survived"] == survived
    assert payload["timeout"] == timed_out
    expected_targets = targets if changed_only else []
    assert payload["targets"] == expected_targets[: mutation._MUTATION_TARGET_LIMIT]
    assert payload["target_count"] == len(expected_targets)
    assert ("truncated_targets" in payload) is (
        len(expected_targets) > mutation._MUTATION_TARGET_LIMIT
    )
    payload_survivors = payload["survivors"]
    assert isinstance(payload_survivors, list)
    assert len(payload_survivors) == min(len(survivors), mutation._MUTATION_SURVIVOR_LIMIT)
    assert ("truncated_survivors" in payload) is (
        len(survivors) > mutation._MUTATION_SURVIVOR_LIMIT
    )


@given(parts=st.lists(_SEGMENT, min_size=1, max_size=4))
def test_mutant_in_changed_matches_exact_or_suffixed_module_path(parts: list[str]) -> None:
    module = ".".join(parts)
    relpath = "/".join(parts) + ".py"
    mutant_key = f"{module}.x_func__mutmut_1"

    assert mutation._mutant_in_changed(mutant_key, {relpath})
    assert mutation._mutant_in_changed(mutant_key, {f"src/{relpath}"})
    assert not mutation._mutant_in_changed(mutant_key, {relpath.removesuffix(".py") + "_x.py"})
