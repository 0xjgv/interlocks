"""Property tests for lintfix patch classification helpers."""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from interlocks.lintfix.budgets import Budget, CandidateCost
from interlocks.lintfix.classify import (
    CandidateMetrics,
    _capture_file,
    _capture_hunk_start,
    _capture_old_file,
    _decide,
    _line_inside,
    _measure,
    _measure_body_line,
    _measure_line,
    _MeasureState,
    _normalize_post_image_path,
    _path_risk_modifier,
    _record_changed_line,
    _score_risk,
    _skip_diff_line,
    classify,
    measure,
)
from interlocks.lintfix.diff import FileHunks, Hunk
from interlocks.lintfix.rules import RulePolicy

_PATHS = st.from_regex(
    r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,20}(?:/[A-Za-z0-9_][A-Za-z0-9_.-]{0,20}){0,3}\.py",
    fullmatch=True,
)
_MODES = st.sampled_from(["auto", "escrow", "advisory", "skip"])


@st.composite
def metrics(draw: Any) -> CandidateMetrics:
    files = tuple(draw(st.lists(_PATHS, unique=True, max_size=12)))
    total = draw(st.integers(min_value=0, max_value=1_000))
    inside = draw(st.integers(min_value=0, max_value=total))
    return CandidateMetrics(
        files_touched=files,
        changed_lines_total=total,
        changed_lines_inside_diff=inside,
        changed_lines_outside_diff=total - inside,
        comment_deletes=draw(st.integers(min_value=0, max_value=20)),
        control_flow_edits=draw(st.integers(min_value=0, max_value=20)),
    )


@given(st.text(max_size=2_000))
def test_measure_never_returns_inconsistent_counts(patch_text: str) -> None:
    measured = measure(patch_text, {})

    assert measured.changed_lines_total >= 0
    assert measured.changed_lines_inside_diff >= 0
    assert measured.changed_lines_outside_diff >= 0
    assert (
        measured.changed_lines_total
        == measured.changed_lines_inside_diff + measured.changed_lines_outside_diff
    )
    assert measured.files_touched == tuple(sorted(set(measured.files_touched)))


@given(st.text(max_size=2_000))
def test_private_measure_matches_public_measure_contract(patch_text: str) -> None:
    assert _measure(patch_text, {}) == measure(patch_text, {})


@given(mode=_MODES, unsafe=st.booleans())
def test_classify_empty_patch_is_skipped_regardless_of_policy(mode: str, unsafe: bool) -> None:
    budget = Budget("generated", 10, 100, 100, 100, allow_unsafe_fixes=True)
    result = classify(
        patch_text="",
        diff_hunks={},
        policy=RulePolicy("R0", mode, "other", 0),  # type: ignore[arg-type]
        budget=budget,
        unsafe=unsafe,
    )

    assert result.mode == "skip"
    assert result.reason == "patch is empty"
    assert result.patch_id == "R0"


@given(patch_text=st.text(max_size=2_000), mode=_MODES, unsafe=st.booleans())
def test_classify_projects_measured_cost_and_rule_identity(
    patch_text: str,
    mode: str,
    unsafe: bool,
) -> None:
    budget = Budget("generated", 10_000, 10_000, 10_000, 10_000, allow_unsafe_fixes=True)
    result = classify(
        patch_text=patch_text,
        diff_hunks={},
        policy=RulePolicy("PX", mode, "other", 3),  # type: ignore[arg-type]
        budget=budget,
        unsafe=unsafe,
    )

    assert result.rule == "PX"
    assert result.patch_id == "PX"
    assert result.cost.files_touched == len(result.metrics.files_touched)
    assert result.cost.changed_lines_total == result.metrics.changed_lines_total
    assert result.cost.changed_lines_outside_diff == result.metrics.changed_lines_outside_diff
    assert result.cost.unsafe is unsafe


@given(mode=_MODES, unsafe=st.booleans(), changed_lines=st.integers(min_value=0, max_value=10))
def test_decide_prioritizes_unsafe_empty_patch_policy_and_budget(
    mode: str,
    unsafe: bool,
    changed_lines: int,
) -> None:
    metrics = CandidateMetrics(("sample.py",), changed_lines, changed_lines, 0, 0, 0)
    cost = CandidateCost(1, changed_lines, 0, 0, unsafe=unsafe)
    budget = Budget("generated", 1, 10, 10, 10, allow_unsafe_fixes=False)

    decided_mode, reason = _decide(mode, metrics, cost, budget)  # type: ignore[arg-type]

    if unsafe:
        assert (decided_mode, reason) == ("skip", "unsafe fix not allowed in default mode")
    elif changed_lines == 0:
        assert (decided_mode, reason) == ("skip", "patch is empty")
    elif mode == "auto":
        assert (decided_mode, reason) == ("auto", None)
    elif mode in {"escrow", "advisory", "skip"}:
        assert decided_mode == mode
        assert reason == f"{mode} by policy"


@given(path=_PATHS, b_prefix=st.booleans())
def test_capture_file_records_git_or_plain_post_image_path(path: str, b_prefix: bool) -> None:
    state = _MeasureState(files=[])
    prefix = "b/" if b_prefix else ""
    expected = f"b/{path}" if b_prefix else path

    assert _capture_file(state, f"+++ {prefix}{path}")
    assert state.current_path == expected
    assert state.files == [expected]


@given(path=_PATHS)
def test_capture_old_file_records_header_without_switching_current_file(path: str) -> None:
    state = _MeasureState(files=[], current_path="previous.py")

    assert _capture_old_file(state, f"--- {path}\tmetadata")
    assert state.old_header_path == path
    assert state.current_path == "previous.py"
    assert state.files == []


@given(line=st.text(max_size=120).filter(lambda value: not value.startswith("--- ")))
def test_capture_old_file_ignores_non_old_file_headers(line: str) -> None:
    state = _MeasureState(files=[], old_header_path="previous.py")

    assert _capture_old_file(state, line) is False
    assert state.old_header_path == "previous.py"


@given(path=_PATHS)
def test_capture_file_strips_git_prefix_with_matching_old_header(path: str) -> None:
    state = _MeasureState(files=[], old_header_path=f"a/{path}")

    assert _capture_file(state, f"+++ b/{path}")
    assert state.current_path == path
    assert state.files == [path]


@given(path=_PATHS)
def test_normalize_post_image_path_strips_only_proven_git_prefixes(path: str) -> None:
    git_path = f"b/{path}"

    assert _normalize_post_image_path(f"a/{path}", git_path) == path
    assert _normalize_post_image_path("/dev/null", git_path) == path
    assert _normalize_post_image_path(None, git_path) == git_path
    assert _normalize_post_image_path(f"a/not-{path}", git_path) == git_path
    assert _normalize_post_image_path(f"a/{path}", path) == path
    assert _normalize_post_image_path(f"a/{path}", "/dev/null") is None


@given(
    start=st.integers(min_value=1, max_value=10_000), count=st.integers(min_value=0, max_value=50)
)
def test_capture_hunk_start_sets_old_line(start: int, count: int) -> None:
    state = _MeasureState(files=[])

    assert _capture_hunk_start(state, f"@@ -{start},{count} +1,1 @@")
    assert state.old_line == start


@given(line=st.text(max_size=80), has_path=st.booleans())
def test_skip_diff_line_requires_current_file_and_real_body_line(
    line: str, has_path: bool
) -> None:
    state = _MeasureState(files=[], current_path="sample.py" if has_path else None)
    expected = (not line) or not has_path or line.startswith(("---", "+++", "diff "))

    assert _skip_diff_line(state, line) is expected


@given(
    path=_PATHS,
    line=st.integers(min_value=1, max_value=100),
    deleted=st.booleans(),
    body=st.sampled_from(["# comment", "if condition:", "value = 1"]),
)
def test_record_changed_line_updates_inside_outside_and_risk_counters(
    path: str,
    line: int,
    deleted: bool,
    body: str,
) -> None:
    state = _MeasureState(files=[path], current_path=path, old_line=line)
    hunks = {path: FileHunks(path, (Hunk(line, line),))}

    _record_changed_line(state, body, hunks, deleted=deleted)

    assert state.total == 1
    assert state.inside == 1
    assert state.outside == 0
    assert state.comment_deletes == (1 if deleted and body.startswith("#") else 0)
    assert state.control_flow_edits == (1 if body.startswith("if ") else 0)
    assert _line_inside(path, line, hunks)


@given(path=_PATHS, line=st.integers(min_value=1, max_value=100), deleted=st.booleans())
def test_record_changed_line_counts_outside_when_line_is_not_in_author_hunks(
    path: str,
    line: int,
    deleted: bool,
) -> None:
    state = _MeasureState(files=[path], current_path=path, old_line=line)
    hunks = {path: FileHunks(path, (Hunk(line + 1, line + 1),))}

    _record_changed_line(state, "value = 1", hunks, deleted=deleted)

    assert state.total == 1
    assert state.inside == 0
    assert state.outside == 1


@given(path=_PATHS)
def test_measure_line_dispatches_post_image_file_headers(path: str) -> None:
    state = _MeasureState(files=[])

    _measure_line(state, f"--- a/{path}", {})
    _measure_line(state, f"+++ b/{path}", {})

    assert state.current_path == path
    assert state.files == [path]


@given(
    prefix=st.sampled_from(["+", "-", " "]),
    body=st.sampled_from(["# comment", "if condition:", "value = 1"]),
    path=_PATHS,
    line=st.integers(min_value=1, max_value=100),
)
def test_measure_body_line_updates_changed_counts_and_old_line(
    prefix: str,
    body: str,
    path: str,
    line: int,
) -> None:
    state = _MeasureState(files=[path], current_path=path, old_line=line)
    hunks = {path: FileHunks(path, (Hunk(line, line),))}

    _measure_body_line(state, f"{prefix}{body}", hunks)

    if prefix == " ":
        assert state.total == 0
        assert state.old_line == line + 1
    else:
        assert state.total == 1
        assert state.inside == 1
        assert state.old_line == (line + 1 if prefix == "-" else line)


@given(
    candidate=metrics(),
    base=st.integers(min_value=-100, max_value=100),
    delta=st.integers(min_value=0, max_value=100),
)
def test_score_risk_is_monotonic_in_base(
    candidate: CandidateMetrics,
    base: int,
    delta: int,
) -> None:
    assert _score_risk(candidate, base=base + delta, unsafe=False) == (
        _score_risk(candidate, base=base, unsafe=False) + delta
    )


@given(candidate=metrics(), base=st.integers(min_value=-100, max_value=100))
def test_unsafe_risk_adds_fixed_penalty(candidate: CandidateMetrics, base: int) -> None:
    safe = _score_risk(candidate, base=base, unsafe=False)
    unsafe = _score_risk(candidate, base=base, unsafe=True)

    assert unsafe == safe + 100


@given(_PATHS)
def test_path_risk_modifier_is_bounded(path: str) -> None:
    assert -2 <= _path_risk_modifier(path) <= 27


@given(path=_PATHS)
def test_path_risk_modifier_scores_migrations_as_risky(path: str) -> None:
    assert _path_risk_modifier(f"app/migrations/{path}") >= 8
