"""Pre-fetch the bundled tool wheels into ``~/.cache/uv``.

Subsequent ``UV_OFFLINE=1 interlocks <stage>`` invocations dispatch through uvx
without touching the network. Two modes:

* When ``interlocks/defaults/tools.txt`` ships hash-pinned wheels (release
  artifact — generated via ``uv pip compile --generate-hashes``), warm uses
  ``uv pip install --require-hashes`` against a throw-away target so every wheel
  is verified and lands in the user's cache.
* Otherwise (development checkout with no ``tools.txt``), warm falls back to
  per-tool uvx probes to populate the cache with the same pins, just without
  hash enforcement. Most tools use ``<entry> --help``; mutmut uses an import
  probe because its command imports project configuration before showing help.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from interlocks import ui
from interlocks.defaults.tools import DEFAULTS, UV_INDEX_FLAG, entrypoint
from interlocks.runner import fail, section, uvx_tool, warn_skip

_WARM_FALLBACK_WARNING = "tools.txt missing — falling back to per-tool uvx probes (no hash check)"
_WARM_PROGRESS_COMMAND_MAX = 80
_WARM_OUTPUT_EXCERPT_MAX = 500
_WARM_OFFLINE_ACTION = "Run gates with `UV_OFFLINE=1` when you need offline execution."
_MUTMUT_IMPORT_PROBE = "import mutmut"


@dataclass(frozen=True)
class _WarmOutcome:
    mode: str
    passed: bool
    cached_tools: tuple[str, ...] = ()
    failed_tools: tuple[str, ...] = ()
    tools_txt: str = ""
    warning: str = ""
    error: str = ""
    output_excerpt: str = ""


def _tools_txt_path() -> Path:
    return Path(__file__).resolve().parent.parent / "defaults" / "tools.txt"


def _warm_via_tools_txt(tools_txt: Path) -> _WarmOutcome:
    """Hash-verified pre-fetch."""
    with tempfile.TemporaryDirectory(prefix="interlocks-warm-") as target_raw:
        target = Path(target_raw)
        _warm_row("tools.txt", "running")
        result = subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--require-hashes",
                "--target",
                str(target),
                "-r",
                str(tools_txt),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            _warm_row(
                "tools.txt",
                "failed",
                detail="warm: hash-pinned pre-fetch failed",
                state="fail",
            )
            if not ui.is_json():
                sys.stdout.write(result.stdout)
                sys.stdout.write(result.stderr)
            return _WarmOutcome(
                mode="tools.txt",
                passed=False,
                tools_txt=str(tools_txt),
                error="hash-pinned pre-fetch failed",
                output_excerpt=_warm_output_excerpt(result.stdout, result.stderr),
            )
        _warm_row(
            "tools.txt",
            "ok",
            detail=f"warm: hash-verified {len(DEFAULTS)} tool(s) cached via tools.txt",
        )
        return _WarmOutcome(
            mode="tools.txt",
            passed=True,
            cached_tools=tuple(_default_tool_specs()),
            tools_txt=str(tools_txt),
        )


def _warm_per_tool() -> _WarmOutcome:
    """Best-effort fallback: probe each pinned tool through uvx so its wheel lands in cache."""
    failed: list[str] = []
    cached: list[str] = []
    for name, version in DEFAULTS.items():
        cmd = _warm_probe_cmd(name, version)
        spec = f"{name}=={version}"
        _warm_row(spec, "running")
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            _warm_row(spec, "ok", detail=f"warm: cached {spec}")
            cached.append(spec)
        else:
            _warm_row(spec, "failed", detail=f"warm: failed to fetch {spec}", state="fail")
            failed.append(spec)
    return _WarmOutcome(
        mode="uvx-probes",
        passed=not failed,
        cached_tools=tuple(cached),
        failed_tools=tuple(failed),
        warning=_WARM_FALLBACK_WARNING,
        error="one or more tools failed to fetch" if failed else "",
    )


def _warm_row(
    command: str,
    status: str,
    *,
    detail: str | None = None,
    state: ui.State = "ok",
) -> None:
    if ui.is_json():
        print(f"interlocks: [warm] {_warm_progress_command(command)} {status}", file=sys.stderr)
        sys.stderr.flush()
        return
    ui.gate_row("warm", command, status, detail=detail, state=state)
    sys.stdout.flush()


def cmd_warm() -> None:
    """Populate ``~/.cache/uv`` with the bundled tool pins so offline runs work."""
    section("Warm uvx cache")
    if shutil.which("uv") is None:
        if ui.is_json():
            ui.print_json(_warm_missing_uv_payload())
            sys.exit(1)
        fail("warm: `uv` not found on PATH; install uv before warming the cache")
        sys.exit(1)
    tools_txt = _tools_txt_path()
    if tools_txt.is_file() and tools_txt.stat().st_size > 0:
        outcome = _warm_via_tools_txt(tools_txt)
        if ui.is_json():
            ui.print_json(_warm_payload(outcome))
        if outcome.passed:
            return
        sys.exit(1)
    if not ui.is_json():
        warn_skip(f"warm: {_WARM_FALLBACK_WARNING}")
        sys.stdout.flush()
    outcome = _warm_per_tool()
    if ui.is_json():
        ui.print_json(_warm_payload(outcome))
    if not outcome.passed:
        sys.exit(1)


def _warm_payload(outcome: _WarmOutcome) -> dict[str, object]:
    payload: dict[str, object] = {
        "command": "warm",
        "passed": outcome.passed,
        "status": "ok" if outcome.passed else "failed",
        "mode": outcome.mode,
        "tool_count": len(DEFAULTS),
        "tools": _default_tool_specs(),
        "cached_tools": list(outcome.cached_tools),
        "failed_tools": list(outcome.failed_tools),
        "next_actions": [_WARM_OFFLINE_ACTION] if outcome.passed else [_warm_failure_action()],
    }
    if outcome.tools_txt:
        payload["tools_txt"] = outcome.tools_txt
    if outcome.warning:
        payload["warnings"] = [outcome.warning]
    if outcome.error:
        payload["error"] = outcome.error
    if outcome.output_excerpt:
        payload["output_excerpt"] = outcome.output_excerpt
    return payload


def _warm_missing_uv_payload() -> dict[str, object]:
    return {
        "command": "warm",
        "passed": False,
        "status": "failed",
        "mode": "preflight",
        "tool_count": len(DEFAULTS),
        "tools": _default_tool_specs(),
        "cached_tools": [],
        "failed_tools": _default_tool_specs(),
        "error": "`uv` not found on PATH",
        "next_actions": ["Install uv, then rerun `interlocks warm --json`."],
    }


def _default_tool_specs() -> list[str]:
    return [f"{name}=={version}" for name, version in DEFAULTS.items()]


def _warm_probe_cmd(name: str, version: str) -> list[str]:
    spec = f"{name}=={version}"
    if name == "interlocks-mutmut":
        return ["uvx", "--from", spec, *UV_INDEX_FLAG, "python", "-c", _MUTMUT_IMPORT_PROBE]
    return uvx_tool(name, "--help", version=version, entrypoint=entrypoint(name))


def _warm_output_excerpt(*chunks: str) -> str:
    text = "\n".join(chunk.strip() for chunk in chunks if chunk.strip())
    if len(text) <= _WARM_OUTPUT_EXCERPT_MAX:
        return text
    return f"{text[: _WARM_OUTPUT_EXCERPT_MAX - 1]}…"


def _warm_failure_action() -> str:
    return "Fix the reported tool-cache failure, then rerun `interlocks warm --json`."


def _warm_progress_command(command: str) -> str:
    if len(command) <= _WARM_PROGRESS_COMMAND_MAX:
        return command
    return f"{command[: _WARM_PROGRESS_COMMAND_MAX - 1]}…"
