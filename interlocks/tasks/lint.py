"""Lint code with ruff (read-only)."""

from __future__ import annotations

import sys
from dataclasses import dataclass

from interlocks import run_summary, ui
from interlocks.config import InterlockConfig, load_config
from interlocks.runner import Task, capture, run, run_task_json, uvx_tool
from interlocks.tasks._ruff import make_ruff_task, ruff_config_args


def task_lint(files: list[str] | None = None) -> Task:
    return make_ruff_task("lint", files)


def cmd_lint(files: list[str] | None = None) -> None:
    cfg = load_config()
    if cfg.preset == "progressive":
        cmd_lint_progressive(files)
        return
    if ui.is_json():
        run_task_json("lint", task_lint(files))
        return
    run(task_lint(files))


_TOP_VIOLATIONS = 10


@dataclass(frozen=True)
class _ProgressiveLintSummary:
    count: int | None
    cap: int | None
    status: str
    passed: bool
    reason: str | None = None
    examples: tuple[str, ...] = ()
    omitted: int = 0


def cmd_lint_progressive(files: list[str] | None = None) -> None:
    """Count ruff violations; record for the ratchet; gate on ``lint_violations_max``."""
    cfg = load_config()
    if ui.is_json():
        print("interlocks: [lint] ruff check running", file=sys.stderr)
    result = capture(_progressive_lint_cmd(cfg, files))
    summary = _progressive_lint_summary(result.returncode, result.stdout, cfg.lint_violations_max)
    if summary.count is not None:
        run_summary.record_lint_count(summary.count)
    if ui.is_json():
        _emit_progressive_lint_json(summary)
        return
    _render_progressive_lint(summary)


def _progressive_lint_cmd(cfg: InterlockConfig, files: list[str] | None) -> list[str]:
    # --quiet drops the trailing "Found N errors" summary so each stdout line is one violation.
    return uvx_tool(
        "ruff",
        "check",
        "--output-format=concise",
        "--quiet",
        *ruff_config_args(),
        *(files or ["."]),
        version=cfg.tool_version("ruff"),
    )


def _progressive_lint_summary(
    returncode: int, stdout: str, cap: int | None
) -> _ProgressiveLintSummary:
    if returncode not in (0, 1):
        return _ProgressiveLintSummary(
            count=None,
            cap=cap,
            status="skipped",
            passed=True,
            reason=f"ruff rc={returncode}",
        )
    lines = tuple(line for line in stdout.splitlines() if line.strip())
    count = len(lines)
    passed = cap is None or count <= cap
    return _ProgressiveLintSummary(
        count=count,
        cap=cap,
        status="ok" if passed else "failed",
        passed=passed,
        examples=lines[:_TOP_VIOLATIONS] if not passed else (),
        omitted=max(0, count - _TOP_VIOLATIONS) if not passed else 0,
    )


def _emit_progressive_lint_json(summary: _ProgressiveLintSummary) -> None:
    ui.print_json(_progressive_lint_payload(summary))
    if not summary.passed:
        sys.exit(1)


def _render_progressive_lint(summary: _ProgressiveLintSummary) -> None:
    if summary.status == "skipped":
        ui.row("lint", "ruff check", "skipped", detail=summary.reason, state="warn")
        return
    count = summary.count or 0
    if summary.cap is None:
        ui.row("lint", "ruff check", f"{count} violations (no cap)", state="ok")
        return
    if summary.passed:
        ui.row("lint", "ruff check", f"{count}/{summary.cap} violations", state="ok")
        return
    ui.row("lint", "ruff check", f"{count} > {summary.cap} violations", state="fail")
    for line in summary.examples:
        print(f"    {line}")
    if summary.omitted > 0:
        print(f"    … {summary.omitted} more")
    sys.exit(1)


def _progressive_lint_payload(summary: _ProgressiveLintSummary) -> dict[str, object]:
    payload: dict[str, object] = {
        "command": "lint",
        "passed": summary.passed,
        "mode": "progressive",
        "status": summary.status,
        "violations": summary.count,
        "limit": summary.cap,
    }
    if summary.reason is not None:
        payload["reason"] = summary.reason
    if summary.examples:
        payload["examples"] = list(summary.examples)
    if summary.omitted > 0:
        payload["omitted"] = summary.omitted
    if not summary.passed:
        payload["next_actions"] = [
            "Reduce lint violations to the progressive baseline or advance the baseline "
            "intentionally."
        ]
    return payload
