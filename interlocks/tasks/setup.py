"""Unified local setup command for interlocks integrations."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from interlocks import ui
from interlocks.config import find_project_root, load_optional_config
from interlocks.defaults_path import path as defaults_path
from interlocks.hook_setup import install_hooks
from interlocks.runner import fail_skip, ok
from interlocks.setup_state import (
    ADVANCE_ARTIFACT,
    CI_ARTIFACTS,
    SetupArtifactStatus,
    advance_workflow_present,
    ci_artifact_statuses,
    ci_workflow_present,
    is_git_repo,
    setup_artifact_statuses,
)
from interlocks.tasks.agents import install_agent_docs
from interlocks.tasks.setup_skill import install_skill

_PROGRESSIVE_RECOMMENDATION = (
    'Run `interlocks presets set progressive` to set preset = "progressive" '
    "for autopilot ratcheting."
)
_SETUP_USAGE = "usage: interlocks setup [--check] [--ci=github]"
_LOCAL_INSTALL_NEXT_ACTIONS = (
    "Run `interlocks check` after edits.",
    "Run `interlocks doctor` to diagnose readiness or failures.",
    "Wire shared CI manually, or run `interlocks setup --ci=github` for GitHub Actions.",
)
_CI_INSTALL_NEXT_ACTIONS = (
    "Run `interlocks setup --ci=github --check` to verify CI wiring.",
    "Commit the workflow file after reviewing the action pin and install-command policy.",
)

if TYPE_CHECKING:
    from pathlib import Path


def cmd_setup() -> None:
    start = time.monotonic()
    args = _parse_args()
    project_root = find_project_root()

    ui.command_banner("setup", load_optional_config())
    if args.ci == "github":
        if args.check_only:
            _cmd_setup_ci_check(project_root)
        else:
            _cmd_setup_ci_install(project_root)
    elif args.check_only:
        _cmd_setup_check(project_root)
    else:
        _cmd_setup_install(project_root)
    ui.command_footer(start)


@dataclass(frozen=True)
class _SetupArgs:
    check_only: bool = False
    ci: Literal["github"] | None = None


def _parse_args() -> _SetupArgs:
    raw = [arg for arg in sys.argv[2:] if arg not in {"--quiet", "--verbose", "--json"}]
    check_only = False
    ci: Literal["github"] | None = None
    for arg in raw:
        if arg == "--check":
            check_only = True
        elif arg == "--ci=github":
            ci = "github"
        elif arg.startswith("--ci="):
            _fail_setup_error("unsupported CI setup target: " + arg.split("=", 1)[1])
        else:
            _fail_setup_error(_SETUP_USAGE)
    return _SetupArgs(check_only=check_only, ci=ci)


def _cmd_setup_install(project_root: Path) -> None:
    if not is_git_repo(project_root):
        _fail_setup_error(
            "setup: not a git repository — run `git init` first, then `interlocks setup`",
            next_actions=["Run `git init`, then rerun `interlocks setup`."],
        )
    ui.section("Setup")
    install_hooks(project_root)
    install_agent_docs(project_root)
    install_skill(project_root)

    statuses = setup_artifact_statuses(project_root)
    if ui.is_json():
        _emit_setup_payload(
            _setup_payload(
                mode="local",
                check_only=False,
                statuses=statuses,
                next_actions=list(_LOCAL_INSTALL_NEXT_ACTIONS),
            )
        )
        return

    ui.section("Status")
    _render_status(statuses)

    if ui.is_verbose():
        ui.section("Next Steps")
        ui.message_list(list(_LOCAL_INSTALL_NEXT_ACTIONS))


def _cmd_setup_ci_install(project_root: Path) -> None:
    ui.section("GitHub CI Setup")
    workflow = project_root / ".github" / "workflows" / "interlocks.yml"
    installed = ci_workflow_present(project_root)
    if installed:
        ok("GitHub workflow already invokes interlocks")
    elif workflow.is_file():
        _fail_setup_error(
            ".github/workflows/interlocks.yml already exists but does not invoke interlocks; "
            "review it before rerunning setup",
            next_actions=[
                "Review the existing workflow, then rerun `interlocks setup --ci=github`."
            ],
        )
    else:
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text(
            defaults_path("github_workflow.yml").read_text(encoding="utf-8"), encoding="utf-8"
        )
        installed = True
        ok("Installed GitHub Actions workflow at .github/workflows/interlocks.yml")
    advance_installed = _maybe_install_advance_workflow(project_root)
    ui.section("Status")
    statuses = [SetupArtifactStatus(CI_ARTIFACTS[0], installed)]
    if advance_installed is not None:
        statuses.append(SetupArtifactStatus(ADVANCE_ARTIFACT, advance_installed))
    if ui.is_json():
        _emit_setup_payload(
            _setup_payload(
                mode="github-ci",
                check_only=False,
                statuses=statuses,
                next_actions=list(_CI_INSTALL_NEXT_ACTIONS),
            )
        )
        return
    _render_status(statuses)
    if ui.is_verbose():
        ui.section("Next Steps")
        ui.message_list(list(_CI_INSTALL_NEXT_ACTIONS))


def _maybe_install_advance_workflow(project_root: Path) -> bool | None:
    """Install the auto-PR advance workflow when preset is ``progressive``.

    Returns ``None`` when not applicable (preset is not progressive), ``True``
    when present after this call, and ``False`` only on a write failure that
    we surface to the caller for status rendering.
    """
    cfg = load_optional_config(project_root)
    if cfg is None or cfg.preset != "progressive":
        return None
    workflow = project_root / ".github" / "workflows" / "interlocks-advance.yml"
    if advance_workflow_present(project_root):
        ok("Advance workflow already installed")
        return True
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text(
        defaults_path("github_workflow_advance.yml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    ok("Installed advance workflow at .github/workflows/interlocks-advance.yml")
    return True


def _cmd_setup_ci_check(project_root: Path) -> None:
    statuses = ci_artifact_statuses(project_root)
    cfg = load_optional_config(project_root)
    if cfg is not None and cfg.preset == "progressive":
        statuses.append(
            SetupArtifactStatus(ADVANCE_ARTIFACT, advance_workflow_present(project_root))
        )
    extra_lines = _progressive_recommendation_lines(project_root)
    if ui.is_json():
        _emit_setup_payload(
            _check_payload(
                mode="github-ci",
                statuses=statuses,
                fix_message=(
                    "Run `interlocks setup --ci=github` to install a GitHub Actions workflow."
                ),
                extra_lines=extra_lines,
            )
        )
        return
    _render_check(
        "GitHub CI Check",
        statuses,
        ok_message="GitHub CI invokes interlocks.",
        fix_message="Run `interlocks setup --ci=github` to install a GitHub Actions workflow.",
        extra_lines=extra_lines,
    )


def _cmd_setup_check(project_root: Path) -> None:
    statuses = setup_artifact_statuses(project_root)
    extra_lines = _progressive_recommendation_lines(project_root)
    if ui.is_json():
        _emit_setup_payload(
            _check_payload(
                mode="local",
                statuses=statuses,
                fix_message="Run `interlocks setup` to install or refresh local integrations.",
                extra_lines=extra_lines,
            )
        )
        return
    _render_check(
        "Setup Check",
        statuses,
        ok_message="Local integrations are installed and current.",
        fix_message="Run `interlocks setup` to install or refresh local integrations.",
        extra_lines=extra_lines,
    )


def _check_payload(
    *,
    mode: str,
    statuses: list[SetupArtifactStatus],
    fix_message: str,
    extra_lines: list[str],
) -> dict[str, object]:
    installed = all(status.installed for status in statuses)
    next_actions = list(extra_lines) if installed else [fix_message, *extra_lines]
    return _setup_payload(
        mode=mode,
        check_only=True,
        statuses=statuses,
        next_actions=next_actions,
    )


def _setup_payload(
    *,
    mode: str,
    check_only: bool,
    statuses: list[SetupArtifactStatus],
    next_actions: list[str],
) -> dict[str, object]:
    installed = all(status.installed for status in statuses)
    return {
        "command": "setup",
        "mode": mode,
        "check": check_only,
        "passed": installed,
        "status": "installed" if installed else "missing/stale",
        "artifacts": [_artifact_payload(status) for status in statuses],
        "next_actions": next_actions,
    }


def _artifact_payload(status: SetupArtifactStatus) -> dict[str, object]:
    return {
        "label": status.label,
        "target": status.target,
        "installed": status.installed,
        "status": "installed" if status.installed else "missing/stale",
    }


def _emit_setup_payload(payload: dict[str, object]) -> None:
    ui.print_json(payload)
    if not payload["passed"]:
        sys.exit(1)


def _fail_setup_error(message: str, *, next_actions: list[str] | None = None) -> None:
    if ui.is_json():
        ui.print_json({
            "command": "setup",
            "passed": False,
            "status": "error",
            "error": message,
            "usage": _SETUP_USAGE,
            "next_actions": next_actions or ["Run `interlocks help setup` for supported flags."],
        })
        sys.exit(1)
    fail_skip(message)


def _progressive_recommendation_lines(project_root: Path) -> list[str]:
    """Recommend ``preset = "progressive"`` when no preset (or ``baseline``) is set."""
    cfg = load_optional_config(project_root)
    if cfg is not None and cfg.preset not in (None, "baseline"):
        return []
    return [_PROGRESSIVE_RECOMMENDATION]


def _render_check(
    title: str,
    statuses: list[SetupArtifactStatus],
    *,
    ok_message: str,
    fix_message: str,
    extra_lines: list[str] | None = None,
) -> None:
    """Render a `--check` section: status table + Next Steps; exit 1 if anything missing."""
    ui.section(title)
    _render_status(statuses)
    if all(status.installed for status in statuses):
        if ui.is_verbose():
            _render_check_next_steps([ok_message, *(extra_lines or [])])
        else:
            _render_check_next_steps(extra_lines or [])
        return
    _render_check_next_steps([fix_message, *(extra_lines or [])])
    sys.exit(1)


def _render_check_next_steps(lines: list[str]) -> None:
    if not lines:
        return
    if ui.is_verbose():
        ui.section("Next Steps")
        ui.message_list(lines)
        return
    for line in lines:
        print(f"next: {line}")


def _render_status(statuses: list[SetupArtifactStatus]) -> None:
    for status in statuses:
        state: ui.State = "ok" if status.installed else "fail"
        ui.row(
            status.label,
            status.target,
            "installed" if status.installed else "missing/stale",
            state=state,
            force=True,
        )
