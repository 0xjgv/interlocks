"""Setup-hooks stage — writes git pre-commit + Claude Code Stop hooks."""

from __future__ import annotations

import json
import shlex
import sys
import time
from pathlib import Path

from harness import ui
from harness.config import load_config
from harness.runner import ok


def _is_post_edit_command(command: object) -> bool:
    return isinstance(command, str) and (
        command.endswith("harness.cli post-edit") or command == "uv run harness post-edit"
    )


def _ensure_stop_hook(settings: dict[str, object], command: str) -> dict[str, object]:
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
        settings["hooks"] = hooks

    stop_entries = hooks.setdefault("Stop", [])
    if not isinstance(stop_entries, list):
        stop_entries = []
        hooks["Stop"] = stop_entries

    hook_entry = {"type": "command", "command": command}
    merged_hooks: list[object] = []

    for entry in stop_entries:
        if not isinstance(entry, dict):
            continue
        nested_hooks = entry.get("hooks")
        if not isinstance(nested_hooks, list):
            continue
        for existing_hook in nested_hooks:
            if not isinstance(existing_hook, dict):
                merged_hooks.append(existing_hook)
                continue
            if existing_hook.get("type") != "command":
                merged_hooks.append(existing_hook)
                continue
            existing_command = existing_hook.get("command")
            if existing_command == command:
                continue
            if _is_post_edit_command(existing_command):
                continue
            merged_hooks.append(existing_hook)

    merged_hooks.append(hook_entry)
    hooks["Stop"] = [{"hooks": merged_hooks}]
    return settings


def cmd_hooks() -> None:
    start = time.monotonic()
    ui.banner(load_config())
    ui.section("Setup Hooks")
    try:
        python = shlex.quote(sys.executable)

        hook = Path(".git/hooks/pre-commit")
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(f"#!/bin/sh\nexec {python} -m harness.cli pre-commit\n", encoding="utf-8")
        hook.chmod(0o755)
        ok("Installed pre-commit hook")

        settings_path = Path(".claude/settings.json")
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            existing = {}
        if not isinstance(existing, dict):
            existing = {}
        existing = _ensure_stop_hook(existing, f"{python} -m harness.cli post-edit")
        settings_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
        ok("Installed Claude Code Stop hook")
    finally:
        ui.stage_footer(time.monotonic() - start)
