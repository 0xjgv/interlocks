"""Discover fixable ruff diagnostics on a file set.

Runs ``ruff check --output-format=json --force-exclude <files>`` once and
returns one :class:`RuleCandidate` per unique rule code that has at least one
diagnostic with an available fix. ``has_safe_fix`` / ``has_unsafe_fix``
mirror the ``fix.applicability`` field on diagnostics so callers can decide
whether to simulate the rule at all.

``ruff check`` exits ``0`` (no diagnostics), ``1`` (diagnostics on stdout),
or ``>=2`` (internal error). We treat ``>=2`` as a hard failure and surface
the returncode; anything below 2 is parsed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from interlocks.config import load_config
from interlocks.runner import capture, uvx_tool
from interlocks.tasks._ruff import ruff_config_args


@dataclass(frozen=True)
class RuleCandidate:
    """One fixable rule discovered on the changed file set.

    ``has_safe_fix`` / ``has_unsafe_fix`` distinguish ruff's two fix tiers:
    safe fixes apply under default mode; unsafe ones need ``--unsafe-fixes``.
    The fix harness never enables unsafe fixes in the unblock path, so a
    rule whose ONLY available fix is unsafe is reported but skipped from
    simulation.
    """

    rule: str
    files: tuple[str, ...]
    has_safe_fix: bool
    has_unsafe_fix: bool
    diagnostic_count: int


@dataclass(frozen=True)
class DiscoveryResult:
    """Outcome of one ``ruff check --output-format=json`` run."""

    candidates: tuple[RuleCandidate, ...]
    returncode: int
    stderr: str


def discover_fixable_rules(files: tuple[str, ...]) -> DiscoveryResult:
    """Run ruff in JSON mode and return one candidate per fixable rule code.

    A rule appears in ``candidates`` iff at least one diagnostic carries a
    non-null ``fix`` object. Diagnostics without a fix are ignored — they
    cannot be auto-resolved at all.
    """
    if not files:
        return DiscoveryResult((), 0, "")
    cfg = load_config()
    cmd = uvx_tool(
        "ruff",
        "check",
        "--output-format=json",
        "--force-exclude",
        *ruff_config_args(),
        *files,
        version=cfg.tool_version("ruff"),
    )
    result = capture(cmd)
    if result.returncode >= 2:
        return DiscoveryResult((), result.returncode, result.stderr)
    candidates = parse_diagnostics(result.stdout)
    return DiscoveryResult(candidates, result.returncode, result.stderr)


def parse_diagnostics(raw: str) -> tuple[RuleCandidate, ...]:
    if not raw.strip():
        return ()
    try:
        diagnostics = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(diagnostics, list):
        return ()

    by_rule: dict[str, _RuleBucket] = {}
    for diag in diagnostics:
        if not isinstance(diag, dict):
            continue
        code = diag.get("code")
        fix = diag.get("fix")
        if not isinstance(code, str) or not isinstance(fix, dict):
            continue
        filename = diag.get("filename")
        applicability = fix.get("applicability")
        bucket = by_rule.setdefault(code, _RuleBucket())
        bucket.count += 1
        if isinstance(filename, str):
            bucket.files.add(filename)
        if applicability == "safe":
            bucket.has_safe = True
        elif applicability == "unsafe":
            bucket.has_unsafe = True

    return tuple(
        RuleCandidate(
            rule=code,
            files=tuple(sorted(bucket.files)),
            has_safe_fix=bucket.has_safe,
            has_unsafe_fix=bucket.has_unsafe,
            diagnostic_count=bucket.count,
        )
        for code, bucket in sorted(by_rule.items())
    )


@dataclass
class _RuleBucket:
    count: int = 0
    has_safe: bool = False
    has_unsafe: bool = False
    files: set[str] = field(default_factory=set)
