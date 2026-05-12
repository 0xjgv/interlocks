"""Offline replay of the fix-planner against historical commits.

Walks the last N first-parent commits on ``base_branch`` (or the current
branch when unspecified), and for each commit drives a temporary git
worktree at that commit through ``interlocks fix-plan``. The plan JSON is
parsed back into :class:`stats.CandidateSample` records.

We use ``git worktree add --detach`` rather than ``git checkout`` so the
caller's working tree stays untouched, and a subprocess invocation rather
than an in-process call so each replayed run gets its own ``load_config``
cache and ruff process.
"""

from __future__ import annotations

import json
import subprocess  # noqa: S404 (boundary tool: git CLI + python -m fix-plan; inputs are trusted SHAs)
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from interlocks.lintfix.stats import CandidateSample
from interlocks.runner import tool

# Heuristic: the canonical ``git revert <sha>`` body starts with
# ``This reverts commit <sha>.`` on its own line. We match the prefix so
# the regex doesn't have to walk variable subject lines.
_REVERT_PREFIX = "This reverts commit "


def _run(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run ``cmd`` in ``cwd`` capturing output; never raises on non-zero rc.

    Wraps :mod:`subprocess` so the boundary-call noqa lives in exactly one
    place. Callers prepend ``runner.tool(...)`` to resolve absolute paths
    for git; the python executable comes from ``sys.executable`` directly.
    """
    return subprocess.run(  # noqa: S603 (cmd is built from trusted SHAs + ``runner.tool``)
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


@dataclass(frozen=True)
class ReplayPoint:
    """One commit's replay result."""

    commit: str
    parent: str
    samples: tuple[CandidateSample, ...]
    error: str | None
    reverted_in: str | None


@dataclass(frozen=True)
class ReplayResult:
    """Outcome of an entire replay session."""

    base_branch: str
    budget_name: str
    requested: int
    points: tuple[ReplayPoint, ...]


def replay_history(
    *,
    base_branch: str,
    n: int,
    budget_name: str,
    repo_root: Path,
) -> ReplayResult:
    """Drive the planner over the last ``n`` commits on ``base_branch``.

    Each point either succeeds (with possibly-empty ``samples``) or carries
    a non-empty ``error`` string. The replay never raises on a per-commit
    failure: data lost on one commit must not block analysis of the others.
    """
    commits = _list_commits(base_branch, n, repo_root)
    points = tuple(_replay_one(commit, budget_name, repo_root, base_branch) for commit in commits)
    return ReplayResult(
        base_branch=base_branch,
        budget_name=budget_name,
        requested=n,
        points=points,
    )


def _list_commits(base_branch: str, n: int, repo_root: Path) -> tuple[str, ...]:
    """Return up to ``n`` first-parent commit SHAs on ``base_branch``, newest first.

    First-parent walks merge commits as a single step on the mainline,
    matching the "merged PRs" framing in the spec. Falls back to an empty
    tuple when the branch is unknown.
    """
    result = _run(
        tool("git", "rev-list", "--first-parent", f"-n{n}", base_branch),
        cwd=repo_root,
    )
    if result.returncode != 0:
        return ()
    return tuple(line for line in result.stdout.splitlines() if line)


def _replay_one(
    commit: str,
    budget_name: str,
    repo_root: Path,
    base_branch: str,
) -> ReplayPoint:
    parent = _first_parent(commit, repo_root)
    if not parent:
        return ReplayPoint(commit, "", (), "no parent commit", None)

    reverted_in = _find_revert(commit, base_branch, repo_root)

    with tempfile.TemporaryDirectory(prefix="lintfix-replay-") as tmp:
        worktree = Path(tmp) / "wt"
        added = _add_worktree(worktree, commit, repo_root)
        if not added:
            return ReplayPoint(commit, parent, (), "git worktree add failed", reverted_in)
        try:
            samples = _run_plan_and_load(worktree, parent, budget_name, commit)
        except _ReplayError as err:
            return ReplayPoint(commit, parent, (), str(err), reverted_in)
        finally:
            _remove_worktree(worktree, repo_root)

    samples = tuple(_attach_revert(s, reverted_in) for s in samples)
    return ReplayPoint(commit, parent, samples, None, reverted_in)


def _first_parent(commit: str, repo_root: Path) -> str:
    result = _run(tool("git", "rev-parse", f"{commit}^"), cwd=repo_root)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _find_revert(commit: str, base_branch: str, repo_root: Path) -> str | None:
    """Return the SHA of a commit on ``base_branch`` that reverts ``commit``, if any.

    ``git log --grep`` against the canonical revert body is fast and stable;
    we don't try to follow ``Revert "..."`` subject lines because their
    contents drift across squash strategies.
    """
    result = _run(
        tool(
            "git",
            "log",
            f"{commit}..{base_branch}",
            f"--grep={_REVERT_PREFIX}{commit}",
            "--format=%H",
            "-n1",
        ),
        cwd=repo_root,
    )
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def _add_worktree(worktree: Path, commit: str, repo_root: Path) -> bool:
    result = _run(
        tool("git", "worktree", "add", "--detach", str(worktree), commit),
        cwd=repo_root,
    )
    return result.returncode == 0


def _remove_worktree(worktree: Path, repo_root: Path) -> None:
    """Best-effort worktree cleanup. Failures here aren't fatal — the temp
    dir will still be wiped by the surrounding ``TemporaryDirectory``."""
    _run(tool("git", "worktree", "remove", "--force", str(worktree)), cwd=repo_root)


class _ReplayError(RuntimeError):
    """Internal: per-commit replay failed in a way we want to surface."""


def _run_plan_and_load(
    worktree: Path,
    parent: str,
    budget_name: str,
    commit: str,
) -> tuple[CandidateSample, ...]:
    proc = _run(
        [
            sys.executable,
            "-m",
            "interlocks.cli",
            "fix-plan",
            f"--base={parent}",
            f"--budget={budget_name}",
        ],
        cwd=worktree,
    )
    if proc.returncode != 0:
        raise _ReplayError(f"fix-plan rc={proc.returncode}: {proc.stderr.strip()[:200]}")

    plan_path = worktree / ".lintfix" / "plan.json"
    if not plan_path.is_file():
        raise _ReplayError("plan.json missing after fix-plan")

    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise _ReplayError(f"plan.json parse error: {err}") from err

    return tuple(_to_sample(c, commit) for c in payload.get("candidates", []))


def _to_sample(candidate: dict, commit: str) -> CandidateSample:
    return CandidateSample(
        rule=candidate["rule"],
        mutation_class=candidate.get("mutation_class", "other"),
        classification=candidate["classification"],
        changed_lines_total=int(candidate.get("changed_lines_total", 0)),
        changed_lines_outside_diff=int(candidate.get("changed_lines_outside_diff", 0)),
        risk=int(candidate.get("risk", 0)),
        unsafe=bool(candidate.get("unsafe")),
        commit=commit,
        reverted_in=None,
    )


def _attach_revert(sample: CandidateSample, reverted_in: str | None) -> CandidateSample:
    if reverted_in is None:
        return sample
    return CandidateSample(
        rule=sample.rule,
        mutation_class=sample.mutation_class,
        classification=sample.classification,
        changed_lines_total=sample.changed_lines_total,
        changed_lines_outside_diff=sample.changed_lines_outside_diff,
        risk=sample.risk,
        unsafe=sample.unsafe,
        commit=sample.commit,
        reverted_in=reverted_in,
    )
