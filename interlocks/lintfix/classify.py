"""Candidate patch classifier.

Computes churn + risk metrics from a unified-diff text, scores risk, and
decides the final mode (``auto``/``escrow``/``advisory``/``skip``) using the
rule policy and budget.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import TYPE_CHECKING

from interlocks.lintfix.budgets import CandidateCost, check_budget

if TYPE_CHECKING:
    from interlocks.lintfix.budgets import Budget
    from interlocks.lintfix.diff import FileHunks
    from interlocks.lintfix.rules import Mode, RulePolicy

# ``git diff`` emits ``+++ b/path``; ``ruff --diff`` emits ``+++ path``. Accept both.
_DIFF_FILE = re.compile(r"^\+\+\+ (?:b/)?(.+?)(?:\t.*)?$")
_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_COMMENT_DELETE = re.compile(r"^\s*#")
_CONTROL_FLOW = re.compile(
    r"^\s*(?:if|elif|else|for|while|with|try|except|finally|return|yield)\b"
)

_RISKY_PATHS: tuple[tuple[str, int], ...] = (
    ("**/migrations/**", 10),
    ("**/settings.py", 6),
    ("**/settings/*.py", 6),
    ("**/admin.py", 4),
    ("**/apps.py", 5),
    ("**/management/commands/**", 2),
)
_TEST_PATHS: tuple[str, ...] = ("tests/**", "test/**", "**/tests/**", "**/test_*.py")


@dataclass(frozen=True)
class CandidateMetrics:
    """Measured properties of a candidate patch."""

    files_touched: tuple[str, ...]
    changed_lines_total: int
    changed_lines_inside_diff: int
    changed_lines_outside_diff: int
    comment_deletes: int
    control_flow_edits: int


@dataclass(frozen=True)
class Classification:
    """Final disposition of a candidate patch."""

    rule: str
    mode: Mode
    metrics: CandidateMetrics
    cost: CandidateCost
    reason: str | None
    patch_id: str


def measure(patch_text: str, hunks: dict[str, FileHunks]) -> CandidateMetrics:
    """Parse a unified diff and return metrics."""
    return _measure(patch_text, hunks)


def classify(
    *,
    patch_text: str,
    diff_hunks: dict[str, FileHunks],
    policy: RulePolicy,
    budget: Budget,
    unsafe: bool = False,
) -> Classification:
    """Score and classify a candidate patch given ``policy`` and ``budget``."""
    metrics = _measure(patch_text, diff_hunks)
    risk = _score_risk(metrics, base=policy.base_risk, unsafe=unsafe)
    cost = CandidateCost(
        files_touched=len(metrics.files_touched),
        changed_lines_total=metrics.changed_lines_total,
        changed_lines_outside_diff=metrics.changed_lines_outside_diff,
        risk=risk,
        unsafe=unsafe,
    )
    mode, reason = _decide(policy.mode, metrics, cost, budget)
    files = metrics.files_touched
    patch_id = ":".join((policy.rule, *files)) if files else policy.rule
    return Classification(
        rule=policy.rule,
        mode=mode,
        metrics=metrics,
        cost=cost,
        reason=reason,
        patch_id=patch_id,
    )


def _decide(
    base_mode: Mode, metrics: CandidateMetrics, cost: CandidateCost, budget: Budget
) -> tuple[Mode, str | None]:
    if metrics.changed_lines_total == 0:
        return ("skip", "patch is empty")
    if base_mode == "auto":
        fail = check_budget(cost, budget)
        if fail is None:
            return ("auto", None)
        return ("escrow", f"auto downgraded to escrow: {fail}")
    if base_mode == "escrow":
        return ("escrow", "escrow by policy")
    if base_mode == "advisory":
        return ("advisory", "advisory by policy")
    return ("skip", "skip by policy")


def _measure(patch_text: str, hunks: dict[str, FileHunks]) -> CandidateMetrics:
    """Walk the unified diff in OLD-line coords (the current-tree coord system).

    The PR's hunks (from ``diff.changed_hunks``) also live in current-tree coords,
    so we can compare ``+`` insertions (positioned at the OLD line they'd appear
    before) and ``-`` deletions (at the OLD line they remove) against the same
    range. ``+`` does NOT advance the OLD pointer; ``-`` and `` `` do.
    """
    files: list[str] = []
    total = inside = outside = 0
    comment_del = ctrl = 0
    current_path: str | None = None
    old_line = 0
    for line in patch_text.splitlines():
        m_file = _DIFF_FILE.match(line)
        if m_file:
            captured = m_file.group(1)
            if captured is None:
                continue
            current_path = captured
            files.append(captured)
            continue
        m_hunk = _HUNK_HEADER.match(line)
        if m_hunk:
            old_line = int(m_hunk.group(1))
            continue
        if not line or current_path is None or line.startswith(("---", "+++", "diff ")):
            continue
        prefix = line[0]
        body = line[1:]
        if prefix == "+":
            total += 1
            if _line_inside(current_path, old_line, hunks):
                inside += 1
            else:
                outside += 1
            if _CONTROL_FLOW.match(body):
                ctrl += 1
        elif prefix == "-":
            total += 1
            if _line_inside(current_path, old_line, hunks):
                inside += 1
            else:
                outside += 1
            if _COMMENT_DELETE.match(body):
                comment_del += 1
            if _CONTROL_FLOW.match(body):
                ctrl += 1
            old_line += 1
        elif prefix == " ":
            old_line += 1
    return CandidateMetrics(
        files_touched=tuple(sorted(set(files))),
        changed_lines_total=total,
        changed_lines_inside_diff=inside,
        changed_lines_outside_diff=outside,
        comment_deletes=comment_del,
        control_flow_edits=ctrl,
    )


def _line_inside(path: str, line: int, hunks: dict[str, FileHunks]) -> bool:
    fh = hunks.get(path)
    return fh is not None and fh.contains(line)


def _score_risk(m: CandidateMetrics, *, base: int, unsafe: bool) -> int:
    risk = base
    risk += min(10, m.changed_lines_outside_diff // 5)
    risk += min(5, len(m.files_touched) // 3)
    if m.comment_deletes > 0:
        risk += 10
    if m.control_flow_edits > 0:
        risk += 10
    if unsafe:
        risk += 100
    for path in m.files_touched:
        risk += _path_risk_modifier(path)
    return risk


def _path_risk_modifier(path: str) -> int:
    modifier = 0
    for pattern, weight in _RISKY_PATHS:
        if fnmatch(path, pattern):
            modifier += weight
    if any(fnmatch(path, p) for p in _TEST_PATHS):
        modifier -= 2
    return modifier
