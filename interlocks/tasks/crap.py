"""CRAP complexity x coverage gate."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

from interlocks import run_summary, ui
from interlocks.config import load_config
from interlocks.git import changed_py_files_vs_main
from interlocks.metrics import (
    compute_crap_rows,
    coverage_cache_is_stale,
    lizard_functions,
    parse_coverage,
)
from interlocks.runner import arg_value, generate_coverage_xml

if TYPE_CHECKING:
    from interlocks.config import InterlockConfig
    from interlocks.metrics import CrapRow

_CRAP_ADVISORY_LIMIT = 5
_CRAP_JSON_OFFENDER_LIMIT = 20
_CRAP_COVERAGE_NEXT_ACTION = "Run `interlocks coverage` before `interlocks crap`."


@dataclass(frozen=True)
class _CrapContext:
    max_crap: float
    enforce_crap: bool
    changed_only: bool
    json_mode: bool
    command: str
    start: float


@dataclass(frozen=True)
class _CrapResult:
    function_count: int
    offenders: list[CrapRow]


@dataclass(frozen=True)
class _CrapPayloadState:
    passed: bool
    status: str
    elapsed: float
    function_count: int
    offenders: list[CrapRow]
    reason: str | None = None
    next_action: str | None = None


def _print_offender(row: CrapRow) -> None:
    if ui.is_json():
        return
    print(
        f"    CRAP={row.crap:6.1f}  CCN={row.ccn:3d}  "
        f"cov={row.coverage * 100:5.1f}%  "
        f"{row.name}@{row.start}-{row.end}@{row.path}"
    )


def cmd_crap(*, emit_json: bool = True) -> None:
    """CRAP = ccn^2 * (1-cov)^3 + ccn per function — lizard + coverage XML.

    Threshold precedence: ``--max=N`` on argv > ``cfg.crap_max`` (default 30.0,
    overridable via ``[tool.interlocks] crap_max``). Blocking depends on
    ``cfg.enforce_crap``.
    """
    cfg = load_config()
    context = _crap_context(cfg, emit_json=emit_json)
    if context.json_mode:
        print(f"interlocks: [crap] {context.command} running", file=sys.stderr)
    changed = changed_py_files_vs_main() if context.changed_only else None
    cov_file = _coverage_xml_or_exit(cfg, context)
    result = _crap_result(cfg, cov_file, context.max_crap, changed)
    _emit_crap_result(context, result)


def _crap_context(cfg: InterlockConfig, *, emit_json: bool) -> _CrapContext:
    max_crap = float(arg_value("--max=", str(cfg.crap_max)))
    return _CrapContext(
        max_crap=max_crap,
        enforce_crap=cfg.enforce_crap,
        changed_only="--changed-only" in sys.argv,
        json_mode=ui.is_json() and emit_json,
        command=f"CRAP --max={max_crap}",
        start=time.monotonic(),
    )


def _coverage_xml_or_exit(cfg: InterlockConfig, context: _CrapContext) -> Path:
    skip_reason = _coverage_skip_reason(cfg)
    if skip_reason is not None:
        _exit_crap_skip(context, skip_reason)

    cov_file = generate_coverage_xml()
    if not cov_file.exists():
        _exit_crap_skip(context, "coverage.xml missing")
    return cov_file


def _crap_result(
    cfg: InterlockConfig,
    cov_file: Path,
    max_crap: float,
    changed: set[str] | None,
) -> _CrapResult:
    cov_map = parse_coverage(cov_file)
    fns = lizard_functions(cfg.src_dir_arg)
    all_rows = compute_crap_rows(fns, cov_map, changed=changed)
    if all_rows:
        run_summary.record_crap_max(max(row.crap for row in all_rows))
    offenders = [row for row in all_rows if row.crap > max_crap]
    offenders.sort(key=lambda r: r.crap, reverse=True)
    return _CrapResult(function_count=len(all_rows), offenders=offenders)


def _emit_crap_result(context: _CrapContext, result: _CrapResult) -> None:
    if context.json_mode:
        passed, status = _crap_status(len(result.offenders), context.enforce_crap)
        ui.print_json(
            _crap_payload(
                context,
                _CrapPayloadState(
                    passed=passed,
                    status=status,
                    elapsed=time.monotonic() - context.start,
                    function_count=result.function_count,
                    offenders=result.offenders,
                ),
            )
        )
        if not passed:
            sys.exit(1)
        return

    if not result.offenders:
        ui.gate_row("crap", context.command, "ok", state="ok")
        return
    ui.gate_row(
        "crap",
        context.command,
        f"{len(result.offenders)} function(s) exceed",
        state="fail",
    )
    for row in result.offenders[:20]:
        _print_offender(row)
    if context.enforce_crap:
        sys.exit(1)


def cmd_crap_cached_advisory(changed: set[str] | None = None) -> None:
    """Print fast advisory CRAP output from fresh cached coverage, or a skip hint."""
    cfg = load_config()
    command = f"CRAP --max={cfg.crap_max}"
    cov_file = _fresh_coverage_xml(cfg, command)
    if cov_file is None:
        return

    cov_map = parse_coverage(cov_file)
    all_rows = compute_crap_rows(lizard_functions(cfg.src_dir_arg), cov_map, changed=changed)
    if all_rows:
        run_summary.record_crap_max(max(row.crap for row in all_rows))
    offenders = [row for row in all_rows if row.crap > cfg.crap_max]
    offenders.sort(key=lambda r: r.crap, reverse=True)
    if not offenders:
        ui.row("crap", command, "ok", state="ok")
        return
    ui.row(
        "crap",
        command,
        f"{len(offenders)} function(s) exceed",
        detail="cached advisory",
        state="warn",
    )
    for row in offenders[:_CRAP_ADVISORY_LIMIT]:
        _print_offender(row)
    if len(offenders) > _CRAP_ADVISORY_LIMIT and not ui.is_json():
        print(f"    … {len(offenders) - _CRAP_ADVISORY_LIMIT} more")


def _fresh_coverage_xml(cfg: InterlockConfig, command: str) -> Path | None:
    skip_reason = _coverage_skip_reason(cfg)
    if skip_reason is not None:
        _skip_crap_advisory(command, skip_reason)
        return None
    cov_file = generate_coverage_xml()
    if not cov_file.exists():
        _skip_crap_advisory(command, "coverage.xml missing")
        return None
    return cov_file


def _skip_crap_advisory(command: str, detail: str) -> None:
    ui.row("crap", command, "skipped", detail=detail, state="warn")


def _exit_crap_skip(context: _CrapContext, reason: str) -> NoReturn:
    _emit_crap_skip(context, reason)
    sys.exit(1)


def _coverage_skip_reason(cfg: InterlockConfig) -> str | None:
    cov_cache = Path(".coverage")
    if not cov_cache.exists():
        return "no coverage cache"
    if coverage_cache_is_stale(cov_cache, cfg):
        return "coverage cache is stale"
    return None


def _emit_crap_skip(context: _CrapContext, reason: str) -> None:
    if context.json_mode:
        ui.print_json(
            _crap_payload(
                context,
                _CrapPayloadState(
                    passed=False,
                    status="skipped",
                    elapsed=time.monotonic() - context.start,
                    function_count=0,
                    offenders=[],
                    reason=reason,
                    next_action=_CRAP_COVERAGE_NEXT_ACTION,
                ),
            )
        )
        return
    ui.gate_row(
        "crap",
        context.command,
        "skipped",
        detail=f"{reason} — {_CRAP_COVERAGE_NEXT_ACTION}",
        state="warn",
    )


def _crap_status(offender_count: int, enforce_crap: bool) -> tuple[bool, str]:
    if offender_count == 0:
        return True, "ok"
    if enforce_crap:
        return False, "failed"
    return True, "warn"


def _crap_payload(context: _CrapContext, state: _CrapPayloadState) -> dict[str, object]:
    visible_offenders = state.offenders[:_CRAP_JSON_OFFENDER_LIMIT]
    payload: dict[str, object] = {
        "command": "crap",
        "passed": state.passed,
        "status": state.status,
        "elapsed_seconds": round(state.elapsed, 3),
        "max_crap": context.max_crap,
        "enforce_crap": context.enforce_crap,
        "changed_only": context.changed_only,
        "function_count": state.function_count,
        "offender_count": len(state.offenders),
        "offenders": [_crap_offender_payload(row) for row in visible_offenders],
    }
    truncated = len(state.offenders) - len(visible_offenders)
    if truncated > 0:
        payload["truncated_count"] = truncated
    if state.reason is not None:
        payload["reason"] = state.reason
    if state.next_action is not None:
        payload["next_action"] = state.next_action
    return payload


def _crap_offender_payload(row: CrapRow) -> dict[str, object]:
    return {
        "path": row.path,
        "name": row.name,
        "start": row.start,
        "end": row.end,
        "ccn": row.ccn,
        "loc": row.loc,
        "coverage": round(row.coverage, 4),
        "crap": round(row.crap, 3),
    }
