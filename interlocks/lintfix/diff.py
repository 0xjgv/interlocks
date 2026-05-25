"""Git diff plumbing for the rule-scoped fix harness.

Resolves the base ref, lists changed Python files, parses post-image hunks
from ``git diff --unified=0``, and answers inside-vs-outside-diff membership
questions used by the classifier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from interlocks.runner import capture

_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_FULL_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_DIFF_GIT_FILE = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_DIFF_OLD_FILE = re.compile(r"^--- (.+?)(?:\t.*)?$")
_DIFF_FILE = re.compile(r"^\+\+\+ (.+?)(?:\t.*)?$")


@dataclass(frozen=True)
class Hunk:
    """A contiguous range of post-image lines (1-based, inclusive)."""

    start: int
    end: int

    def contains(self, line: int) -> bool:
        return self.start <= line <= self.end

    def overlaps(self, other: Hunk) -> bool:
        return self.start <= other.end and other.start <= self.end


@dataclass(frozen=True)
class FileHunks:
    """Post-image hunks for one file relative to a base ref."""

    path: str
    hunks: tuple[Hunk, ...]

    def contains(self, line: int) -> bool:
        return any(h.contains(line) for h in self.hunks)


@dataclass(frozen=True)
class AuthorEditCost:
    """Deletion-aware author diff cost used to size mutation budgets."""

    additions: int
    deletions: int
    replacement_pairs: int
    deleted_file_lines: int

    @property
    def total(self) -> int:
        return self.additions + self.deletions + self.replacement_pairs


@dataclass
class _AuthorEditTotals:
    additions: int = 0
    deletions: int = 0
    replacement_pairs: int = 0
    deleted_file_lines: int = 0

    def as_cost(self) -> AuthorEditCost:
        return AuthorEditCost(
            self.additions,
            self.deletions,
            self.replacement_pairs,
            self.deleted_file_lines,
        )


@dataclass
class _DiffParseState:
    current_path: str | None = None
    old_header_path: str | None = None
    git_post_path: str | None = None


def resolve_base(base: str) -> str:
    """Return ``merge-base(base, HEAD)`` or empty string when ``base`` is unknown."""
    return capture(["git", "merge-base", base, "HEAD"]).stdout.strip()


def head_sha() -> str:
    """Return the current HEAD commit SHA, or empty string when unavailable."""
    return capture(["git", "rev-parse", "HEAD"]).stdout.strip()


def changed_files(base: str) -> tuple[str, ...]:
    """Return .py files differing from ``base`` (tracked + untracked), sorted."""
    if not base:
        return ()
    diff = capture(["git", "diff", "--name-only", "--diff-filter=d", base])
    untracked = capture(["git", "ls-files", "--others", "--exclude-standard"])
    files = set(diff.stdout.splitlines()) | set(untracked.stdout.splitlines())
    return tuple(sorted(f for f in files if f.endswith(".py")))


def deleted_files(base: str) -> tuple[str, ...]:
    """Return deleted .py files differing from ``base``."""
    if not base:
        return ()
    diff = capture(["git", "diff", "--name-only", "--diff-filter=D", base])
    return tuple(sorted(f for f in diff.stdout.splitlines() if f.endswith(".py")))


def author_edit_cost(base: str, files: tuple[str, ...] | None = None) -> AuthorEditCost:
    """Return deletion-aware cost for the current author diff vs ``base``.

    ``files`` may limit the calculation to surviving mutation input files. Deleted
    Python files are always included because they affect review surface while
    remaining invalid Ruff inputs.
    """
    if not base:
        return AuthorEditCost(0, 0, 0, 0)
    args = ["git", "diff", "--numstat", base]
    if files:
        args.extend(["--", *files])
    result = capture(args)
    deleted = set(deleted_files(base))
    totals = _AuthorEditTotals()
    counted_deleted: set[str] = set()
    for line in result.stdout.splitlines():
        counted = _add_numstat_line(totals, line, deleted)
        if counted is not None:
            counted_deleted.add(counted)
    if files:
        _add_scoped_deleted_lines(totals, base, counted_deleted=counted_deleted)
    return totals.as_cost()


def _add_numstat_line(totals: _AuthorEditTotals, line: str, deleted: set[str]) -> str | None:
    parts = line.split("\t")
    if len(parts) < 3 or parts[0] == "-" or parts[1] == "-":
        return None
    try:
        added = int(parts[0])
        removed = int(parts[1])
    except ValueError:
        return None
    if added < 0 or removed < 0:
        return None
    totals.additions += added
    totals.deletions += removed
    totals.replacement_pairs += min(added, removed)
    if parts[-1] in deleted:
        totals.deleted_file_lines += removed
        return parts[-1]
    return None


def _add_scoped_deleted_lines(
    totals: _AuthorEditTotals, base: str, *, counted_deleted: set[str]
) -> None:
    deleted_result = capture(["git", "diff", "--numstat", "--diff-filter=D", base])
    for line in deleted_result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[-1] in counted_deleted:
            continue
        removed = _deleted_numstat_removed(line)
        totals.deletions += removed
        totals.deleted_file_lines += removed


def _deleted_numstat_removed(line: str) -> int:
    parts = line.split("\t")
    if len(parts) < 3 or parts[1] == "-" or not parts[-1].endswith(".py"):
        return 0
    try:
        return int(parts[1])
    except ValueError:
        return 0


def changed_hunks(base: str, files: tuple[str, ...]) -> dict[str, FileHunks]:
    """Parse ``git diff --unified=0 <base>`` into ``{path: FileHunks}``.

    Files that are added wholesale (no prior version) have one synthetic hunk
    spanning the whole file. Pure-deletion hunks (post-image count of 0) are
    skipped — they don't claim any post-image lines.
    """
    if not base or not files:
        return {}
    diff = capture(["git", "diff", "--unified=0", base, "--", *files])
    parsed = _parse_diff(diff.stdout)
    # Untracked files won't appear in the diff; treat them as fully-changed.
    for f in files:
        parsed.setdefault(f, FileHunks(f, (_full_file_hunk(f),)))
    return parsed


def _parse_diff(text: str) -> dict[str, FileHunks]:
    by_file = _parse_post_image_hunks(text, _HUNK_HEADER, start_group=1, count_group=2)
    return {path: FileHunks(path, tuple(hunks)) for path, hunks in by_file.items()}


def changed_line_ranges_from_patch(text: str) -> dict[str, tuple[Hunk, ...]]:
    """Return post-image changed ranges from a unified patch."""
    by_file = _parse_post_image_hunks(text, _FULL_HUNK_HEADER, start_group=3, count_group=4)
    return {path: tuple(hunks) for path, hunks in by_file.items()}


def _parse_post_image_hunks(
    text: str,
    hunk_header: re.Pattern[str],
    *,
    start_group: int,
    count_group: int,
) -> dict[str, list[Hunk]]:
    by_file: dict[str, list[Hunk]] = {}
    state = _DiffParseState()
    for line in text.splitlines():
        if _capture_diff_header(line, state, by_file):
            continue
        hunk = _hunk_from_header(
            line, hunk_header, start_group=start_group, count_group=count_group
        )
        if hunk is None or state.current_path is None:
            continue
        by_file[state.current_path].append(hunk)
    return by_file


def _capture_diff_header(
    line: str, state: _DiffParseState, by_file: dict[str, list[Hunk]]
) -> bool:
    is_git_header, git_path = _git_post_image_path(line)
    if is_git_header:
        state.git_post_path = git_path
        return True
    is_old_header, old_path = _pre_image_path(line)
    if is_old_header:
        state.old_header_path = old_path
        return True
    is_file_header, path = _post_image_path(line)
    if not is_file_header:
        return False
    state.current_path = _normalize_post_image_path(
        state.old_header_path, path, git_post_path=state.git_post_path
    )
    state.old_header_path = None
    state.git_post_path = None
    if state.current_path is not None:
        by_file.setdefault(state.current_path, [])
    return True


def _hunk_from_header(
    line: str,
    hunk_header: re.Pattern[str],
    *,
    start_group: int,
    count_group: int,
) -> Hunk | None:
    match = hunk_header.match(line)
    if match is None:
        return None
    start = int(match.group(start_group))
    count = int(match.group(count_group) or "1")
    if count == 0:
        return None
    return Hunk(start, start + count - 1)


def _git_post_image_path(line: str) -> tuple[bool, str | None]:
    """Return whether ``line`` is a Git diff header and its post-image path."""
    m_file = _DIFF_GIT_FILE.match(line)
    if m_file is None:
        return False, None
    return True, m_file.group(2)


def _pre_image_path(line: str) -> tuple[bool, str | None]:
    """Return whether ``line`` is a pre-image file header and its raw path."""
    m_file = _DIFF_OLD_FILE.match(line)
    if m_file is None:
        return False, None
    return True, m_file.group(1)


def _post_image_path(line: str) -> tuple[bool, str | None]:
    """Return whether ``line`` is a post-image file header and its raw path."""
    m_file = _DIFF_FILE.match(line)
    if m_file is None:
        return False, None
    path = m_file.group(1)
    if path == "/dev/null":
        return True, None
    return True, path


def _normalize_post_image_path(
    old_path: str | None, new_path: str | None, *, git_post_path: str | None = None
) -> str | None:
    """Strip Git's ``b/`` prefix only when paired header context proves it."""
    if new_path is None:
        return None
    if not new_path.startswith("b/"):
        return new_path
    stripped = new_path[2:]
    if old_path in ("/dev/null", f"a/{stripped}") or git_post_path == stripped:
        return stripped
    return new_path


def _full_file_hunk(path: str) -> Hunk:
    """A synthetic hunk covering an entire (likely-new) file. Best-effort line count."""
    try:
        with open(path, encoding="utf-8") as f:  # noqa: PTH123 - simple stdlib read
            count = sum(1 for _ in f) or 1
    except OSError:
        count = 1
    return Hunk(1, count)
