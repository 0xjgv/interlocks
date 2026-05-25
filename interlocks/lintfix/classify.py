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

# ``git diff`` emits ``--- a/path`` / ``+++ b/path``; ``ruff --diff`` emits
# plain paths. Do not strip a leading ``b/`` unless the paired old header proves
# it is Git's post-image prefix; projects can contain real ``b/...`` paths.
_DIFF_OLD_FILE = re.compile(r"^--- (.+?)(?:\t.*)?$")
_DIFF_FILE = re.compile(r"^\+\+\+ (.+?)(?:\t.*)?$")
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


@dataclass
class _MeasureState:
    files: list[str]
    total: int = 0
    inside: int = 0
    outside: int = 0
    comment_deletes: int = 0
    control_flow_edits: int = 0
    current_path: str | None = None
    old_line: int = 0
    old_header_path: str | None = None


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


@dataclass(frozen=True)
class ToolPatchCost:
    """Reusable cost summary for one unified tool patch."""

    cost: CandidateCost
    metrics: CandidateMetrics


def measure(patch_text: str, hunks: dict[str, FileHunks]) -> CandidateMetrics:
    """Parse a unified diff and return metrics."""
    return _measure(patch_text, hunks)


def measure_tool_patch_cost(
    patch_text: str,
    hunks: dict[str, FileHunks],
    *,
    base_risk: int = 0,
    unsafe: bool = False,
) -> ToolPatchCost:
    """Measure edit volume, outside-author-hunk churn, files, and risk signals."""
    metrics = _measure(patch_text, hunks)
    cost = CandidateCost(
        files_touched=len(metrics.files_touched),
        changed_lines_total=metrics.changed_lines_total,
        changed_lines_outside_diff=metrics.changed_lines_outside_diff,
        risk=_score_risk(metrics, base=base_risk, unsafe=unsafe),
        unsafe=unsafe,
    )
    return ToolPatchCost(cost=cost, metrics=metrics)


def classify(
    *,
    patch_text: str,
    diff_hunks: dict[str, FileHunks],
    policy: RulePolicy,
    budget: Budget,
    unsafe: bool = False,
) -> Classification:
    """Score and classify a candidate patch given ``policy`` and ``budget``."""
    patch_cost = measure_tool_patch_cost(
        patch_text,
        diff_hunks,
        base_risk=policy.base_risk,
        unsafe=unsafe,
    )
    metrics = patch_cost.metrics
    cost = patch_cost.cost
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


_POLICY_DECISIONS: dict[str, tuple[str, str]] = {
    "escrow": ("escrow", "escrow by policy"),
    "advisory": ("advisory", "advisory by policy"),
    "skip": ("skip", "skip by policy"),
}


def _decide(
    base_mode: Mode, metrics: CandidateMetrics, cost: CandidateCost, budget: Budget
) -> tuple[Mode, str | None]:
    if cost.unsafe and not budget.allow_unsafe_fixes:
        return ("skip", "unsafe fix not allowed in default mode")
    if metrics.changed_lines_total == 0:
        return ("skip", "patch is empty")
    if base_mode == "auto":
        fail = check_budget(cost, budget)
        if fail is None:
            return ("auto", None)
        return ("escrow", f"auto downgraded to escrow: {fail}")
    return _POLICY_DECISIONS.get(base_mode, ("skip", "skip by policy"))  # type: ignore[return-value]


def _measure(patch_text: str, hunks: dict[str, FileHunks]) -> CandidateMetrics:
    """Walk the unified diff in OLD-line coords (the current-tree coord system).

    The PR's hunks (from ``diff.changed_hunks``) also live in current-tree coords,
    so we can compare ``+`` insertions (positioned at the OLD line they'd appear
    before) and ``-`` deletions (at the OLD line they remove) against the same
    range. ``+`` does NOT advance the OLD pointer; ``-`` and `` `` do.
    """
    state = _MeasureState(files=[])
    for line in patch_text.splitlines():
        _measure_line(state, line, hunks)
    return _metrics_from_state(state)


def _measure_line(state: _MeasureState, line: str, hunks: dict[str, FileHunks]) -> None:
    if _capture_old_file(state, line):
        return
    if _capture_file(state, line):
        return
    if _capture_hunk_start(state, line):
        return
    if _skip_diff_line(state, line):
        return
    _measure_body_line(state, line, hunks)


def _capture_old_file(state: _MeasureState, line: str) -> bool:
    match = _DIFF_OLD_FILE.match(line)
    if match is None:
        return False
    state.old_header_path = match.group(1)
    return True


def _capture_file(state: _MeasureState, line: str) -> bool:
    match = _DIFF_FILE.match(line)
    if match is None:
        return False
    captured = _normalize_post_image_path(state.old_header_path, match.group(1))
    state.old_header_path = None
    if captured is not None:
        state.current_path = captured
        state.files.append(captured)
    return True


def _normalize_post_image_path(old_path: str | None, new_path: str) -> str | None:
    if new_path == "/dev/null":
        return None
    if new_path.startswith("b/") and (old_path == "/dev/null" or old_path == f"a/{new_path[2:]}"):
        return new_path[2:]
    return new_path


def _capture_hunk_start(state: _MeasureState, line: str) -> bool:
    match = _HUNK_HEADER.match(line)
    if match is None:
        return False
    state.old_line = int(match.group(1))
    return True


def _skip_diff_line(state: _MeasureState, line: str) -> bool:
    return not line or state.current_path is None or line.startswith(("---", "+++", "diff "))


def _measure_body_line(state: _MeasureState, line: str, hunks: dict[str, FileHunks]) -> None:
    prefix = line[0]
    body = line[1:]
    if prefix == "+":
        _record_changed_line(state, body, hunks, deleted=False)
    elif prefix == "-":
        _record_changed_line(state, body, hunks, deleted=True)
        state.old_line += 1
    elif prefix == " ":
        state.old_line += 1


def _record_changed_line(
    state: _MeasureState,
    body: str,
    hunks: dict[str, FileHunks],
    *,
    deleted: bool,
) -> None:
    state.total += 1
    if _line_inside(state.current_path or "", state.old_line, hunks):
        state.inside += 1
    else:
        state.outside += 1
    if deleted and _COMMENT_DELETE.match(body):
        state.comment_deletes += 1
    if _CONTROL_FLOW.match(body):
        state.control_flow_edits += 1


def _metrics_from_state(state: _MeasureState) -> CandidateMetrics:
    return CandidateMetrics(
        files_touched=tuple(sorted(set(state.files))),
        changed_lines_total=state.total,
        changed_lines_inside_diff=state.inside,
        changed_lines_outside_diff=state.outside,
        comment_deletes=state.comment_deletes,
        control_flow_edits=state.control_flow_edits,
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
