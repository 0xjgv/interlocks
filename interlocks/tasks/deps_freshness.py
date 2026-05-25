"""Dependency freshness via explicit package-index lookup."""

from __future__ import annotations

import json
import shutil
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from interlocks import ui
from interlocks.config import InterlockConfig, invoker_prefix, load_config
from interlocks.detect import detect_target_interpreter
from interlocks.runner import capture, dump_and_exit, warn_skip

if TYPE_CHECKING:
    from subprocess import CompletedProcess


@dataclass(frozen=True)
class _FreshnessLookup:
    command: str
    returncode: int
    stdout: str
    stderr: str
    used_fallback: bool
    elapsed: float


def freshness_cmd(cfg: InterlockConfig) -> list[str]:
    return [*invoker_prefix(cfg), "pip", "list", "--outdated", "--format=json"]


def cmd_deps_freshness() -> None:
    lookup = _run_freshness_lookup(load_config())
    if ui.is_json():
        _emit_freshness_json(lookup)
        return
    _emit_freshness_human(lookup)


def _run_freshness_lookup(cfg: InterlockConfig) -> _FreshnessLookup:
    start = time.monotonic()
    cmd = freshness_cmd(cfg)
    command = "pip list --outdated"
    _freshness_progress(command)
    result = capture(cmd)
    used_fallback = False
    if _missing_pip(result) and shutil.which("uv") is not None:
        _freshness_retry_notice()
        sys.stdout.flush()
        cmd = _uv_pip_list_cmd(cfg)
        command = "uv pip list --outdated"
        used_fallback = True
        _freshness_progress(command)
        result = capture(cmd)
    return _FreshnessLookup(
        command=command,
        returncode=result.returncode,
        stdout=result.stdout or "",
        stderr=result.stderr or "",
        used_fallback=used_fallback,
        elapsed=time.monotonic() - start,
    )


def _emit_freshness_human(lookup: _FreshnessLookup) -> None:
    if lookup.returncode != 0:
        _freshness_row(
            "package-index lookup",
            "failed",
            detail="Dependency freshness: package-index lookup failed",
            state="fail",
        )
        dump_and_exit(lookup.returncode, lookup.stdout, lookup.stderr)

    outdated = _outdated_packages(lookup.stdout)
    if not outdated:
        _freshness_row(
            "package-index lookup",
            "ok",
            detail="Dependency freshness: dependencies current",
        )
        return

    _freshness_row(
        "package-index lookup",
        "failed",
        detail=f"Dependency freshness: {len(outdated)} outdated package(s)",
        state="fail",
    )
    for pkg in outdated:
        print(
            f"  - {pkg.get('name', '?')}: "
            f"{pkg.get('version', '?')} -> {pkg.get('latest_version', '?')}"
        )
    sys.exit(1)


def _emit_freshness_json(lookup: _FreshnessLookup) -> None:
    payload = _freshness_payload(lookup)
    ui.print_json(payload)
    if not payload["passed"]:
        sys.exit(lookup.returncode if lookup.returncode != 0 else 1)


def _uv_pip_list_cmd(cfg: InterlockConfig) -> list[str]:
    venv_python = detect_target_interpreter(cfg.project_root)
    if venv_python is None:
        return ["uv", "pip", "list", "--outdated", "--format=json"]
    return [
        "uv",
        "pip",
        "list",
        "--python",
        str(venv_python),
        "--outdated",
        "--format=json",
    ]


def _missing_pip(result: CompletedProcess[str]) -> bool:
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode != 0 and "No module named pip" in output


def _freshness_row(
    command: str,
    status: str,
    *,
    detail: str | None = None,
    state: ui.State = "ok",
) -> None:
    ui.gate_row("freshness", command, status, detail=detail, state=state)
    sys.stdout.flush()


def _freshness_progress(command: str) -> None:
    if ui.is_json():
        print(f"interlocks: [freshness] {command} running", file=sys.stderr)
        sys.stderr.flush()
        return
    _freshness_row(command, "running")


def _freshness_retry_notice() -> None:
    message = "deps-freshness: target Python has no pip module; retrying with `uv pip list`"
    if ui.is_json():
        print(f"interlocks: [freshness] {message}", file=sys.stderr)
        sys.stderr.flush()
        return
    warn_skip(message)


def _outdated_packages(output: str) -> list[dict[str, object]]:
    try:
        data = json.loads(output or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [package for package in data if isinstance(package, dict)]


def _freshness_payload(lookup: _FreshnessLookup) -> dict[str, object]:
    payload: dict[str, object] = {
        "command": "deps-freshness",
        "lookup_command": lookup.command,
        "fallback_used": lookup.used_fallback,
        "elapsed_seconds": round(lookup.elapsed, 3),
    }
    if lookup.returncode != 0:
        payload.update({
            "passed": False,
            "status": "failed",
            "reason": "package-index lookup failed",
            "returncode": lookup.returncode,
        })
        return payload
    outdated = _outdated_packages(lookup.stdout)
    payload["outdated_count"] = len(outdated)
    payload["outdated"] = outdated
    if not outdated:
        payload.update({"passed": True, "status": "ok"})
        return payload
    payload.update({
        "passed": False,
        "status": "failed",
        "next_actions": [
            "Upgrade outdated dependencies or record an accepted freshness exception."
        ],
    })
    return payload
