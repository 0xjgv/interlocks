"""Property tests for lintfix diff parsing."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from hypothesis import given
from hypothesis import strategies as st

from interlocks.lintfix import diff as diff_mod
from interlocks.lintfix.diff import (
    _HUNK_HEADER,
    FileHunks,
    Hunk,
    _add_numstat_line,
    _add_scoped_deleted_lines,
    _AuthorEditTotals,
    _capture_diff_header,
    _deleted_numstat_removed,
    _DiffParseState,
    _git_post_image_path,
    _hunk_from_header,
    _normalize_post_image_path,
    _parse_diff,
    _parse_post_image_hunks,
    _post_image_path,
    _pre_image_path,
    author_edit_cost,
    changed_hunks,
    changed_line_ranges_from_patch,
    deleted_files,
    resolve_base,
)

_PATHS = st.from_regex(
    r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,20}(?:/[A-Za-z0-9_][A-Za-z0-9_.-]{0,20}){0,2}\.py",
    fullmatch=True,
)
_LINES = st.integers(min_value=1, max_value=10_000)
_COUNTS = st.integers(min_value=0, max_value=1_000)
_NON_PY_PATHS = st.from_regex(
    r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,20}\.(?:txt|md|json|toml)",
    fullmatch=True,
)
_LINE_TEXT = st.text(
    alphabet=st.characters(blacklist_characters="\r\n"),
    max_size=40,
)


def _expected_hunks(start: int, count: int) -> tuple[Hunk, ...]:
    if count == 0:
        return ()
    return (Hunk(start, start + count - 1),)


@given(old_path=_PATHS, new_path=_PATHS)
def test_git_post_image_path_extracts_new_git_path(old_path: str, new_path: str) -> None:
    assert _git_post_image_path(f"diff --git a/{old_path} b/{new_path}") == (True, new_path)


@given(_LINE_TEXT.filter(lambda line: not line.startswith("diff --git a/")))
def test_git_post_image_path_rejects_non_git_diff_lines(line: str) -> None:
    assert _git_post_image_path(line) == (False, None)


@given(path=_PATHS, metadata=_LINE_TEXT)
def test_pre_image_path_extracts_raw_old_header(path: str, metadata: str) -> None:
    suffix = f"\t{metadata}" if metadata else ""

    assert _pre_image_path(f"--- {path}{suffix}") == (True, path)


@given(_LINE_TEXT.filter(lambda line: not line.startswith("--- ")))
def test_pre_image_path_rejects_non_old_headers(line: str) -> None:
    assert _pre_image_path(line) == (False, None)


@given(path=_PATHS)
def test_capture_diff_header_tracks_git_context(path: str) -> None:
    state = _DiffParseState()
    by_file: dict[str, list[Hunk]] = {}

    assert _capture_diff_header(f"diff --git a/old.py b/{path}", state, by_file)
    assert state.git_post_path == path
    assert by_file == {}


@given(path=_PATHS)
def test_capture_diff_header_registers_normalized_post_image_path(path: str) -> None:
    state = _DiffParseState(old_header_path=f"a/{path}")
    by_file: dict[str, list[Hunk]] = {}

    assert _capture_diff_header(f"+++ b/{path}", state, by_file)
    assert state.current_path == path
    assert state.old_header_path is None
    assert state.git_post_path is None
    assert by_file == {path: []}


@given(_LINE_TEXT.filter(lambda line: not line.startswith(("diff --git a/", "--- ", "+++ "))))
def test_capture_diff_header_rejects_non_headers_without_mutation(line: str) -> None:
    state = _DiffParseState(
        current_path="current.py",
        old_header_path="a/current.py",
        git_post_path="current.py",
    )
    by_file = {"current.py": [Hunk(1, 1)]}

    assert not _capture_diff_header(line, state, by_file)
    assert state == _DiffParseState(
        current_path="current.py",
        old_header_path="a/current.py",
        git_post_path="current.py",
    )
    assert by_file == {"current.py": [Hunk(1, 1)]}


@given(path=_PATHS, b_prefix=st.booleans(), metadata=_LINE_TEXT)
def test_post_image_path_extracts_git_headers(
    path: str,
    b_prefix: bool,
    metadata: str,
) -> None:
    prefix = "b/" if b_prefix else ""
    suffix = f"\t{metadata}" if metadata else ""

    assert _post_image_path(f"+++ {prefix}{path}{suffix}") == (True, f"{prefix}{path}")


@given(path=_PATHS)
def test_normalize_post_image_path_strips_only_proven_git_prefixes(path: str) -> None:
    git_path = f"b/{path}"

    assert _normalize_post_image_path(f"a/{path}", git_path) == path
    assert _normalize_post_image_path("/dev/null", git_path) == path
    assert _normalize_post_image_path("a/old.py", git_path, git_post_path=path) == path
    assert _normalize_post_image_path(path, git_path) == git_path
    assert _normalize_post_image_path(None, git_path) == git_path


@given(metadata=_LINE_TEXT)
def test_post_image_path_resets_deleted_files(metadata: str) -> None:
    suffix = f"\t{metadata}" if metadata else ""

    assert _post_image_path(f"+++ /dev/null{suffix}") == (True, None)


@given(_LINE_TEXT.filter(lambda line: not line.startswith("+++ ")))
def test_post_image_path_rejects_non_post_image_lines(line: str) -> None:
    assert _post_image_path(line) == (False, None)


@given(line=_LINES, start=_LINES, end=_LINES)
def test_hunk_membership_and_overlap_are_closed_interval(
    line: int,
    start: int,
    end: int,
) -> None:
    lo, hi = sorted((start, end))
    hunk = Hunk(lo, hi)
    other = Hunk(line, line)

    assert hunk.contains(line) is (lo <= line <= hi)
    assert hunk.overlaps(other) is hunk.contains(line)


@given(line=_LINES, ranges=st.lists(st.tuples(_LINES, _LINES), max_size=20))
def test_file_hunks_contains_matches_any_member_hunk(
    line: int,
    ranges: list[tuple[int, int]],
) -> None:
    hunks = tuple(Hunk(min(start, end), max(start, end)) for start, end in ranges)
    file_hunks = FileHunks("generated.py", hunks)

    assert FileHunks.contains(file_hunks, line) is any(Hunk.contains(hunk, line) for hunk in hunks)


@given(line=_LINES)
def test_file_hunks_contains_is_false_without_hunks(line: int) -> None:
    file_hunks = FileHunks("generated.py", ())

    assert FileHunks.contains(file_hunks, line) is False


@given(st.text(max_size=2_000))
def test_diff_parsers_never_return_invalid_hunks(raw: str) -> None:
    parsed = _parse_diff(raw)
    ranges = changed_line_ranges_from_patch(raw)

    assert all(path == file_hunks.path for path, file_hunks in parsed.items())
    assert all(
        hunk.start <= hunk.end for file_hunks in parsed.values() for hunk in file_hunks.hunks
    )
    assert all(hunk.start <= hunk.end for hunks in ranges.values() for hunk in hunks)


@given(start=_LINES, count=_COUNTS)
def test_hunk_from_header_returns_post_image_interval(start: int, count: int) -> None:
    line = f"@@ -1,1 +{start},{count} @@"
    expected = None if count == 0 else Hunk(start, start + count - 1)

    assert _hunk_from_header(line, _HUNK_HEADER, start_group=1, count_group=2) == expected


@given(start=_LINES)
def test_hunk_from_header_defaults_missing_count_to_single_line(start: int) -> None:
    line = f"@@ -1 +{start} @@"

    assert _hunk_from_header(line, _HUNK_HEADER, start_group=1, count_group=2) == Hunk(
        start, start
    )


@given(path=_PATHS, start=_LINES, count=_COUNTS)
def test_parse_post_image_hunks_returns_normalized_file_hunks(
    path: str,
    start: int,
    count: int,
) -> None:
    patch = f"""\
--- a/{path}
+++ b/{path}
@@ -1,1 +{start},{count} @@
"""

    assert _parse_post_image_hunks(patch, _HUNK_HEADER, start_group=1, count_group=2) == {
        path: list(_expected_hunks(start, count))
    }


@given(files=st.one_of(st.none(), st.lists(_PATHS, max_size=5).map(tuple)))
def test_author_edit_cost_empty_base_returns_zero_cost(files: tuple[str, ...] | None) -> None:
    cost = author_edit_cost("", files=files)

    assert cost.additions == 0
    assert cost.deletions == 0
    assert cost.replacement_pairs == 0
    assert cost.deleted_file_lines == 0
    assert cost.total == 0


@given(
    path=_PATHS,
    first_start=_LINES,
    first_count=_COUNTS,
    second_start=_LINES,
    second_count=_COUNTS,
)
def test_parse_post_image_hunks_preserves_multiple_hunks_for_one_file(
    path: str,
    first_start: int,
    first_count: int,
    second_start: int,
    second_count: int,
) -> None:
    patch = f"""\
--- a/{path}
+++ b/{path}
@@ -1,1 +{first_start},{first_count} @@
@@ -2,1 +{second_start},{second_count} @@
"""
    expected = [
        *_expected_hunks(first_start, first_count),
        *_expected_hunks(second_start, second_count),
    ]

    assert _parse_post_image_hunks(patch, _HUNK_HEADER, start_group=1, count_group=2) == {
        path: expected
    }


@given(path=_PATHS, start=_LINES, count=_COUNTS)
def test_parse_post_image_hunks_ignores_hunks_before_file_header(
    path: str,
    start: int,
    count: int,
) -> None:
    patch = f"""\
@@ -9,1 +999,1 @@
--- a/{path}
+++ b/{path}
@@ -1,1 +{start},{count} @@
"""

    assert _parse_post_image_hunks(patch, _HUNK_HEADER, start_group=1, count_group=2) == {
        path: list(_expected_hunks(start, count))
    }


@given(path=_PATHS, old_start=_LINES, old_count=_COUNTS, new_start=_LINES, new_count=_COUNTS)
def test_parse_diff_returns_post_image_ranges(
    path: str,
    old_start: int,
    old_count: int,
    new_start: int,
    new_count: int,
) -> None:
    patch = f"""\
--- a/{path}
+++ b/{path}
@@ -{old_start},{old_count} +{new_start},{new_count} @@
"""

    assert _parse_diff(patch) == {path: FileHunks(path, _expected_hunks(new_start, new_count))}


@given(path=_PATHS, old_start=_LINES, old_count=_COUNTS, new_start=_LINES, new_count=_COUNTS)
def test_changed_line_ranges_from_patch_returns_post_image_ranges(
    path: str,
    old_start: int,
    old_count: int,
    new_start: int,
    new_count: int,
) -> None:
    patch = f"""\
--- a/{path}
+++ b/{path}
@@ -{old_start},{old_count} +{new_start},{new_count} @@
"""

    assert changed_line_ranges_from_patch(patch) == {path: _expected_hunks(new_start, new_count)}


@given(previous_path=_PATHS, deleted_path=_PATHS, deleted_start=_LINES, deleted_count=_COUNTS)
def test_parse_diff_skips_dev_null_post_image(
    previous_path: str,
    deleted_path: str,
    deleted_start: int,
    deleted_count: int,
) -> None:
    patch = f"""\
--- a/{previous_path}
+++ b/{previous_path}
@@ -1,1 +1,2 @@
--- a/{deleted_path}
+++ /dev/null
@@ -1,1 +{deleted_start},{deleted_count} @@
"""

    assert _parse_diff(patch) == {previous_path: FileHunks(previous_path, (Hunk(1, 2),))}


@given(previous_path=_PATHS, deleted_path=_PATHS, deleted_start=_LINES, deleted_count=_COUNTS)
def test_dev_null_post_image_resets_active_file(
    previous_path: str,
    deleted_path: str,
    deleted_start: int,
    deleted_count: int,
) -> None:
    patch = f"""\
--- a/{previous_path}
+++ b/{previous_path}
@@ -1,1 +1,2 @@
--- a/{deleted_path}
+++ /dev/null
@@ -1,1 +{deleted_start},{deleted_count} @@
"""

    assert changed_line_ranges_from_patch(patch) == {previous_path: (Hunk(1, 2),)}


@given(
    added=st.integers(min_value=0, max_value=1_000_000),
    removed=st.integers(min_value=0, max_value=1_000_000),
    path=_PATHS,
    is_deleted=st.booleans(),
)
def test_numstat_line_updates_author_edit_totals(
    added: int,
    removed: int,
    path: str,
    is_deleted: bool,
) -> None:
    totals = _AuthorEditTotals()
    deleted = {path} if is_deleted else set()

    counted = _add_numstat_line(totals, f"{added}\t{removed}\t{path}", deleted)

    assert totals.additions == added
    assert totals.deletions == removed
    assert totals.replacement_pairs == min(added, removed)
    assert totals.deleted_file_lines == (removed if is_deleted else 0)
    assert counted == (path if is_deleted else None)


@given(raw=st.text(max_size=500), deleted=st.sets(_PATHS, max_size=5))
def test_numstat_line_ignores_malformed_or_negative_rows(raw: str, deleted: set[str]) -> None:
    totals = _AuthorEditTotals()

    counted = _add_numstat_line(totals, raw, deleted)

    assert counted is None or counted in deleted
    assert totals.additions >= 0
    assert totals.deletions >= 0
    assert totals.replacement_pairs >= 0
    assert totals.deleted_file_lines >= 0


@given(st.text(max_size=500))
def test_deleted_numstat_removed_never_raises(raw: str) -> None:
    assert _deleted_numstat_removed(raw) >= 0


@given(removed=st.integers(min_value=0, max_value=1_000_000), path=_PATHS)
def test_deleted_numstat_removed_extracts_python_deletions(removed: int, path: str) -> None:
    assert _deleted_numstat_removed(f"0\t{removed}\t{path}") == removed


def test_add_numstat_line_ignores_binary_rows_without_mutation() -> None:
    totals = _AuthorEditTotals(additions=1, deletions=2, replacement_pairs=3, deleted_file_lines=4)

    counted = _add_numstat_line(totals, "-\t-\tdeleted.py", {"deleted.py"})

    assert counted is None
    assert totals == _AuthorEditTotals(
        additions=1,
        deletions=2,
        replacement_pairs=3,
        deleted_file_lines=4,
    )


@given(removed=st.integers(min_value=0, max_value=1_000_000), path=_NON_PY_PATHS)
def test_deleted_numstat_removed_ignores_non_python_deletions(
    removed: int,
    path: str,
) -> None:
    assert _deleted_numstat_removed(f"0\t{removed}\t{path}") == 0


@given(base=st.text(max_size=30), stdout=st.text(max_size=200))
def test_resolve_base_strips_merge_base_stdout(base: str, stdout: str) -> None:
    calls: list[list[str]] = []

    def fake_capture(cmd: list[str]) -> SimpleNamespace:
        calls.append(cmd)
        return SimpleNamespace(stdout=stdout)

    original = diff_mod.capture
    diff_mod.capture = fake_capture  # type: ignore[assignment]
    try:
        resolved = resolve_base(base)
    finally:
        diff_mod.capture = original

    assert calls == [["git", "merge-base", base, "HEAD"]]
    assert resolved == stdout.strip()


@given(paths=st.lists(st.one_of(_PATHS, _NON_PY_PATHS), max_size=20))
def test_deleted_files_returns_sorted_python_paths(paths: list[str]) -> None:
    def fake_capture(cmd: list[str]) -> SimpleNamespace:
        assert cmd == ["git", "diff", "--name-only", "--diff-filter=D", "base"]
        return SimpleNamespace(stdout="\n".join(paths))

    original = diff_mod.capture
    diff_mod.capture = fake_capture  # type: ignore[assignment]
    try:
        deleted = deleted_files("base")
    finally:
        diff_mod.capture = original

    assert deleted == tuple(sorted(path for path in paths if path.endswith(".py")))


@given(
    rows=st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=1_000),
            st.integers(min_value=0, max_value=1_000),
            _PATHS,
            st.booleans(),
        ),
        max_size=20,
    )
)
def test_author_edit_cost_aggregates_numstat_rows(rows: list[tuple[int, int, str, bool]]) -> None:
    deleted = {path for _added, _removed, path, is_deleted in rows if is_deleted}
    numstat = "\n".join(f"{added}\t{removed}\t{path}" for added, removed, path, _ in rows)

    def fake_capture(cmd: list[str]) -> SimpleNamespace:
        if cmd == ["git", "diff", "--numstat", "base"]:
            return SimpleNamespace(stdout=numstat)
        if cmd == ["git", "diff", "--name-only", "--diff-filter=D", "base"]:
            return SimpleNamespace(stdout="\n".join(deleted))
        raise AssertionError(cmd)

    original = diff_mod.capture
    diff_mod.capture = fake_capture  # type: ignore[assignment]
    try:
        cost = author_edit_cost("base")
    finally:
        diff_mod.capture = original

    assert cost.additions == sum(added for added, _removed, _path, _is_deleted in rows)
    assert cost.deletions == sum(removed for _added, removed, _path, _is_deleted in rows)
    assert cost.replacement_pairs == sum(
        min(added, removed) for added, removed, _path, _is_deleted in rows
    )
    assert cost.deleted_file_lines == sum(
        removed for _added, removed, path, _is_deleted in rows if path in deleted
    )


@given(path=_PATHS, line_count=st.integers(min_value=1, max_value=30))
def test_changed_hunks_treats_diff_absent_files_as_full_file(path: str, line_count: int) -> None:
    def fake_capture(cmd: list[str]) -> SimpleNamespace:
        assert cmd == ["git", "diff", "--unified=0", "base", "--", path]
        return SimpleNamespace(stdout="")

    original_capture = diff_mod.capture
    old_cwd = Path.cwd()
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x\n" * line_count, encoding="utf-8")
        os.chdir(root)
        diff_mod.capture = fake_capture  # type: ignore[assignment]
        try:
            parsed = changed_hunks("base", (path,))
        finally:
            diff_mod.capture = original_capture
            os.chdir(old_cwd)

    assert parsed == {path: FileHunks(path, (Hunk(1, line_count),))}


@given(path=_PATHS, start=_LINES, count=st.integers(min_value=1, max_value=30))
def test_changed_hunks_parses_git_diff_output(path: str, start: int, count: int) -> None:
    diff = f"--- a/{path}\n+++ b/{path}\n@@ -1,1 +{start},{count} @@\n"

    def fake_capture(cmd: list[str]) -> SimpleNamespace:
        assert cmd == ["git", "diff", "--unified=0", "base", "--", path]
        return SimpleNamespace(stdout=diff)

    original = diff_mod.capture
    diff_mod.capture = fake_capture  # type: ignore[assignment]
    try:
        parsed = changed_hunks("base", (path,))
    finally:
        diff_mod.capture = original

    assert parsed == {path: FileHunks(path, (Hunk(start, start + count - 1),))}


@given(
    rows=st.lists(st.tuples(st.integers(min_value=0, max_value=1000), _PATHS), max_size=20),
    counted=st.sets(_PATHS, max_size=10),
)
def test_add_scoped_deleted_lines_skips_already_counted_deleted_files(
    rows: list[tuple[int, str]], counted: set[str]
) -> None:
    totals = _AuthorEditTotals()
    stdout = "\n".join(f"0\t{removed}\t{path}" for removed, path in rows)

    def fake_capture(cmd: list[str]) -> SimpleNamespace:
        assert cmd == ["git", "diff", "--numstat", "--diff-filter=D", "base"]
        return SimpleNamespace(stdout=stdout)

    original = diff_mod.capture
    diff_mod.capture = fake_capture  # type: ignore[assignment]
    try:
        _add_scoped_deleted_lines(totals, "base", counted_deleted=counted)
    finally:
        diff_mod.capture = original

    expected_removed = sum(removed for removed, path in rows if path not in counted)
    assert totals.deletions == expected_removed
    assert totals.deleted_file_lines == expected_removed
