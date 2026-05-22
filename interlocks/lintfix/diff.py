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
_DIFF_FILE = re.compile(r"^\+\+\+ (?:b/)?(.+?)(?:\t.*)?$")


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
    for line in result.stdout.splitlines():
        _add_numstat_line(totals, line, deleted)
    if files:
        _add_scoped_deleted_lines(totals, base)
    return totals.as_cost()


def _add_numstat_line(totals: _AuthorEditTotals, line: str, deleted: set[str]) -> None:
    parts = line.split("\t")
    if len(parts) < 3 or parts[0] == "-" or parts[1] == "-":
        return
    added = int(parts[0])
    removed = int(parts[1])
    totals.additions += added
    totals.deletions += removed
    totals.replacement_pairs += min(added, removed)
    if parts[-1] in deleted:
        totals.deleted_file_lines += removed


def _add_scoped_deleted_lines(totals: _AuthorEditTotals, base: str) -> None:
    deleted_result = capture(["git", "diff", "--numstat", "--diff-filter=D", base])
    for line in deleted_result.stdout.splitlines():
        removed = _deleted_numstat_removed(line)
        totals.deletions += removed
        totals.deleted_file_lines += removed


def _deleted_numstat_removed(line: str) -> int:
    parts = line.split("\t")
    if len(parts) < 3 or parts[1] == "-" or not parts[-1].endswith(".py"):
        return 0
    return int(parts[1])


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
    current_path: str | None = None
    by_file: dict[str, list[Hunk]] = {}
    for line in text.splitlines():
        m_file = _DIFF_FILE.match(line)
        if m_file:
            captured = m_file.group(1)
            if captured is None:
                continue
            current_path = captured
            by_file.setdefault(captured, [])
            continue
        m_hunk = _HUNK_HEADER.match(line)
        if m_hunk is None or current_path is None:
            continue
        start = int(m_hunk.group(1))
        count = int(m_hunk.group(2) or "1")
        if count == 0:
            continue
        by_file[current_path].append(Hunk(start, start + count - 1))
    return {path: FileHunks(path, tuple(hunks)) for path, hunks in by_file.items()}


def changed_line_ranges_from_patch(text: str) -> dict[str, tuple[Hunk, ...]]:
    """Return post-image changed ranges from a unified patch."""
    by_file: dict[str, list[Hunk]] = {}
    current_path: str | None = None
    for line in text.splitlines():
        m_file = _DIFF_FILE.match(line)
        if m_file:
            captured = m_file.group(1)
            # The widened `_DIFF_FILE` regex also matches a deletion hunk's
            # `+++ /dev/null` line — it claims no post-image lines.
            if captured is None or captured == "/dev/null":
                continue
            current_path = captured
            by_file.setdefault(captured, [])
            continue
        m_hunk = _FULL_HUNK_HEADER.match(line)
        if m_hunk is None or current_path is None:
            continue
        start = int(m_hunk.group(3))
        count = int(m_hunk.group(4) or "1")
        if count:
            by_file[current_path].append(Hunk(start, start + count - 1))
    return {path: tuple(hunks) for path, hunks in by_file.items()}


def _full_file_hunk(path: str) -> Hunk:
    """A synthetic hunk covering an entire (likely-new) file. Best-effort line count."""
    try:
        with open(path, encoding="utf-8") as f:  # noqa: PTH123 - simple stdlib read
            count = sum(1 for _ in f) or 1
    except OSError:
        count = 1
    return Hunk(1, count)
