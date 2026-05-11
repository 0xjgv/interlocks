"""Lint code with ruff (read-only)."""

from __future__ import annotations

import sys

from interlocks import run_summary, ui
from interlocks.config import load_config
from interlocks.runner import Task, capture, run, uvx_tool
from interlocks.tasks._ruff import make_ruff_task, ruff_config_args


def task_lint(files: list[str] | None = None) -> Task:
    return make_ruff_task("lint", files)


def cmd_lint(files: list[str] | None = None) -> None:
    cfg = load_config()
    if cfg.preset == "progressive":
        cmd_lint_progressive(files)
        return
    run(task_lint(files))


_TOP_VIOLATIONS = 10


def cmd_lint_progressive(files: list[str] | None = None) -> None:
    """Count ruff violations; record for the ratchet; gate on ``lint_violations_max``."""
    cfg = load_config()
    # --quiet drops the trailing "Found N errors" summary so each stdout line is one violation.
    cmd = uvx_tool(
        "ruff",
        "check",
        "--output-format=concise",
        "--quiet",
        *ruff_config_args(),
        *(files or ["."]),
        version=cfg.tool_version("ruff"),
    )
    result = capture(cmd)
    # rc 0 = clean, rc 1 = violations found (fine, we count them), rc ≥ 2 = ruff crashed.
    if result.returncode not in (0, 1):
        detail = f"ruff rc={result.returncode}"
        ui.row("lint", "ruff check", "skipped", detail=detail, state="warn")
        return
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    count = len(lines)
    run_summary.record_lint_count(count)
    cap = cfg.lint_violations_max
    if cap is None:
        ui.row("lint", "ruff check", f"{count} violations (no cap)", state="ok")
        return
    if count <= cap:
        ui.row("lint", "ruff check", f"{count}/{cap} violations", state="ok")
        return
    ui.row("lint", "ruff check", f"{count} > {cap} violations", state="fail")
    for line in lines[:_TOP_VIOLATIONS]:
        print(f"    {line}")
    extra = count - _TOP_VIOLATIONS
    if extra > 0:
        print(f"    … {extra} more")
    sys.exit(1)
