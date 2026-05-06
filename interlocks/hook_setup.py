"""Install local hook integrations."""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path
from typing import TypeVar

from interlocks.runner import ok
from interlocks.setup_state import is_post_edit_command

_Container = TypeVar("_Container", dict[str, object], list[object])


def _reset_invalid_container(parent: dict[str, object], key: str, empty: _Container) -> _Container:
    """Return ``parent[key]`` when it matches ``type(empty)``; reset to ``empty`` otherwise."""
    value = parent.setdefault(key, empty)
    if isinstance(value, type(empty)):
        return value  # pyright: ignore[reportReturnType]
    parent[key] = empty
    return empty


def _keep_existing_hook(hook: object, new_command: str) -> bool:
    """Keep non-command hooks; drop duplicates of ``new_command`` or prior post-edit entries."""
    if not isinstance(hook, dict):
        return True
    if hook.get("type") != "command":
        return True
    existing = hook.get("command")
    if existing == new_command:
        return False
    return not is_post_edit_command(existing)


def _ensure_stop_hook(settings: dict[str, object], command: str) -> dict[str, object]:
    hooks = _reset_invalid_container(settings, "hooks", {})
    stop_entries = _reset_invalid_container(hooks, "Stop", [])
    merged_hooks: list[object] = [
        hook
        for entry in stop_entries
        if isinstance(entry, dict) and isinstance(entry.get("hooks"), list)
        for hook in entry["hooks"]
        if _keep_existing_hook(hook, command)
    ]
    merged_hooks.append({"type": "command", "command": command})
    hooks["Stop"] = [{"hooks": merged_hooks}]
    return settings


def install_hooks(project_root: Path | None = None) -> None:
    root = project_root or Path.cwd()
    python = shlex.quote(sys.executable)

    hook = root / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    script = f"#!/bin/sh\nexec {python} -m interlocks.cli pre-commit\n"
    hook.write_text(script, encoding="utf-8")
    hook.chmod(0o755)
    ok("Installed pre-commit hook")

    settings_path = root / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = json.loads(settings_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        existing = {}
    if not isinstance(existing, dict):
        existing = {}
    existing = _ensure_stop_hook(existing, f"{python} -m interlocks.cli post-edit")
    settings_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    ok("Installed Claude Code Stop hook")
