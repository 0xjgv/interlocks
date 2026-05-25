"""Setup-hooks stage — writes git pre-commit + Claude Code Stop hooks."""

from __future__ import annotations

import time
from pathlib import Path

from interlocks import ui
from interlocks.config import load_optional_config
from interlocks.hook_setup import install_hooks
from interlocks.setup_state import SETUP_ARTIFACTS, SetupArtifactStatus, artifact_statuses

_SETUP_HOOKS_NEXT_ACTIONS = ("Run `interlocks setup --check` to verify all local integrations.",)


def cmd_hooks() -> None:
    start = time.monotonic()
    project_root = Path()
    ui.command_banner("setup-hooks", load_optional_config())
    ui.section("Setup Hooks")
    try:
        _install_and_render_hooks(project_root)
    finally:
        ui.stage_footer(time.monotonic() - start)


def _install_and_render_hooks(project_root: Path) -> None:
    before = _hook_statuses(project_root)
    install_hooks(project_root)
    after = _hook_statuses(project_root)
    if ui.is_json():
        ui.print_json(_setup_hooks_payload(before, after))
        return
    _render_hook_statuses(after)


def _hook_statuses(project_root: Path) -> list[SetupArtifactStatus]:
    return artifact_statuses(SETUP_ARTIFACTS[:2], project_root)


def _setup_hooks_payload(
    before: list[SetupArtifactStatus],
    after: list[SetupArtifactStatus],
) -> dict[str, object]:
    installed = all(status.installed for status in after)
    return {
        "command": "setup-hooks",
        "passed": installed,
        "status": "installed" if installed else "missing/stale",
        "installed": installed,
        "hooks": [
            _hook_payload(before_status, after_status)
            for before_status, after_status in zip(before, after, strict=True)
        ],
        "next_actions": list(_SETUP_HOOKS_NEXT_ACTIONS),
    }


def _hook_payload(
    before: SetupArtifactStatus,
    after: SetupArtifactStatus,
) -> dict[str, object]:
    return {
        "label": after.label,
        "target": after.target,
        "action": "refreshed" if before.installed else "installed",
        "installed": after.installed,
    }


def _render_hook_statuses(statuses: list[SetupArtifactStatus]) -> None:
    for status in statuses:
        state: ui.State = "ok" if status.installed else "fail"
        ui.row(
            status.label,
            status.target,
            "installed" if status.installed else "missing/stale",
            state=state,
            force=True,
        )
