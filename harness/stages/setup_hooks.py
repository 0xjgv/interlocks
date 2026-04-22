"""Setup-hooks stage — writes git pre-commit + Claude Code Stop hooks."""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path


def cmd_hooks() -> None:
    python = shlex.quote(sys.executable)

    hook = Path(".git/hooks/pre-commit")
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(f"#!/bin/sh\nexec {python} -m harness.cli pre-commit\n", encoding="utf-8")
    hook.chmod(0o755)
    print("Installed pre-commit hook")

    settings_path = Path(".claude/settings.json")
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = json.loads(settings_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        existing = {}
    existing.setdefault("hooks", {}).setdefault("Stop", [])
    entry = {"command": f"{python} -m harness.cli post-edit"}
    if entry not in existing["hooks"]["Stop"]:
        existing["hooks"]["Stop"].append(entry)
    settings_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    print("Installed Claude Code Stop hook")
