"""Rule-scoped ruff simulation.

Runs ``ruff check --select <RULE> --fix --diff --force-exclude <files>`` to
preview a candidate patch without mutating the working tree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from interlocks.config import load_config
from interlocks.runner import capture, uvx_tool
from interlocks.tasks._ruff import ruff_config_args

if TYPE_CHECKING:
    import subprocess


@dataclass(frozen=True)
class CandidatePatch:
    """One rule-scoped diff plus the ruff exit code that produced it."""

    rule: str
    files: tuple[str, ...]
    diff: str
    returncode: int


def simulate_rule(rule: str, files: tuple[str, ...]) -> CandidatePatch:
    """Return the candidate patch for ``rule`` over ``files`` (non-mutating)."""
    if not files:
        return CandidatePatch(rule, (), "", 0)
    cfg = load_config()
    cmd = uvx_tool(
        "ruff",
        "check",
        f"--select={rule}",
        "--fix",
        "--diff",
        "--force-exclude",
        *ruff_config_args(),
        *files,
        version=cfg.tool_version("ruff"),
    )
    result = capture(cmd)
    return CandidatePatch(rule, files, result.stdout, result.returncode)


def apply_rule(rule: str, files: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    """Apply ``rule`` to ``files`` in the working tree (auto-mode only).

    Callers MUST gate this behind a budget check and final verification.
    """
    cfg = load_config()
    cmd = uvx_tool(
        "ruff",
        "check",
        f"--select={rule}",
        "--fix",
        "--force-exclude",
        *ruff_config_args(),
        *files,
        version=cfg.tool_version("ruff"),
    )
    return capture(cmd)
