"""Install the bundled Claude Code SKILL.md into the consumer repo.

Copies ``interlocks/defaults/skill/SKILL.md`` to
``.claude/skills/interlocks/SKILL.md`` in the current working directory.
Idempotent: a byte-identical copy is a no-op; a divergent copy is overwritten
(the file is tool-managed, not user-edited). Stdlib-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from interlocks import ui
from interlocks.defaults_path import path as defaults_path
from interlocks.runner import ok, section, warn_skip
from interlocks.setup_state import SKILL_DEST, skill_installed

_SETUP_SKILL_NEXT_ACTIONS = ("Use the installed Claude skill when working in this repo.",)


@dataclass(frozen=True)
class SkillInstallResult:
    path: Path
    action: str
    installed: bool


def cmd_setup_skill() -> None:
    section("Install Claude Code skill")
    project_root = Path.cwd()
    result = install_skill(project_root)
    if ui.is_json():
        ui.print_json(_setup_skill_payload(project_root, result))
        return
    _render_skill_status(project_root)


def install_skill(project_root: Path | None = None) -> SkillInstallResult:
    bundled = defaults_path("skill/SKILL.md").read_text(encoding="utf-8")
    root = project_root or Path.cwd()
    dest = root / SKILL_DEST
    try:
        existing = dest.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = None
    if existing == bundled:
        warn_skip(f"{SKILL_DEST} already installed — skipped")
        return SkillInstallResult(path=dest, action="kept", installed=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(bundled, encoding="utf-8")
    action = "updated" if existing is not None else "installed"
    ok(f"{action} {SKILL_DEST}")
    return SkillInstallResult(path=dest, action=action, installed=True)


def _setup_skill_payload(project_root: Path, result: SkillInstallResult) -> dict[str, object]:
    installed = result.installed and skill_installed(project_root)
    return {
        "command": "setup-skill",
        "passed": True,
        "status": "installed" if installed else "missing/stale",
        "installed": installed,
        "path": _project_relative(project_root, result.path),
        "action": result.action,
        "next_actions": list(_SETUP_SKILL_NEXT_ACTIONS),
    }


def _project_relative(project_root: Path, path: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


def _render_skill_status(project_root: Path) -> None:
    installed = skill_installed(project_root)
    state: ui.State = "ok" if installed else "fail"
    ui.row(
        "claude skill",
        str(SKILL_DEST),
        "installed" if installed else "missing/stale",
        state=state,
        force=True,
    )
