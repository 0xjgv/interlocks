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
    CI_ARTIFACTS,
    SetupArtifactStatus,
    ci_artifact_statuses,
    ci_workflow_present,
    setup_artifact_statuses,
)
from interlocks.tasks.agents import install_agent_docs
from interlocks.tasks.setup_skill import install_skill

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
    raw = [arg for arg in sys.argv[2:] if arg not in {"--quiet", "--verbose"}]
    check_only = False
    ci: Literal["github"] | None = None
    for arg in raw:
        if arg == "--check":
            check_only = True
        elif arg == "--ci=github":
            ci = "github"
        elif arg.startswith("--ci="):
            fail_skip("unsupported CI setup target: " + arg.split("=", 1)[1])
        else:
            fail_skip("usage: interlocks setup [--check] [--ci=github]")
    return _SetupArgs(check_only=check_only, ci=ci)


def _cmd_setup_install(project_root: Path) -> None:
    ui.section("Setup")
    install_hooks(project_root)
    install_agent_docs(project_root)
    install_skill(project_root)

    ui.section("Status")
    _render_status(setup_artifact_statuses(project_root))

    ui.section("Next Steps")
    ui.message_list([
        "Run `interlocks check` after edits.",
        "Run `interlocks doctor` to diagnose readiness or failures.",
        "Wire shared CI manually, or run `interlocks setup --ci=github` for GitHub Actions.",
    ])


def _cmd_setup_ci_install(project_root: Path) -> None:
    ui.section("GitHub CI Setup")
    workflow = project_root / ".github" / "workflows" / "interlocks.yml"
    installed = ci_workflow_present(project_root)
    if installed:
        ok("GitHub workflow already invokes interlocks")
    elif workflow.is_file():
        fail_skip(
            ".github/workflows/interlocks.yml already exists but does not invoke interlocks; "
            "review it before rerunning setup"
        )
    else:
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text(
            defaults_path("github_workflow.yml").read_text(encoding="utf-8"), encoding="utf-8"
        )
        installed = True
        ok("Installed GitHub Actions workflow at .github/workflows/interlocks.yml")
    ui.section("Status")
    _render_status([SetupArtifactStatus(CI_ARTIFACTS[0], installed)])
    ui.section("Next Steps")
    ui.message_list([
        "Run `interlocks setup --ci=github --check` to verify CI wiring.",
        "Commit the workflow file after reviewing the action pin and install-command policy.",
    ])


def _cmd_setup_ci_check(project_root: Path) -> None:
    _render_check(
        "GitHub CI Check",
        ci_artifact_statuses(project_root),
        ok_message="GitHub CI invokes interlocks.",
        fix_message="Run `interlocks setup --ci=github` to install a GitHub Actions workflow.",
    )


def _cmd_setup_check(project_root: Path) -> None:
    _render_check(
        "Setup Check",
        setup_artifact_statuses(project_root),
        ok_message="Local integrations are installed and current.",
        fix_message="Run `interlocks setup` to install or refresh local integrations.",
    )


def _render_check(
    title: str,
    statuses: list[SetupArtifactStatus],
    *,
    ok_message: str,
    fix_message: str,
) -> None:
    """Render a `--check` section: status table + Next Steps; exit 1 if anything missing."""
    ui.section(title)
    _render_status(statuses)
    ui.section("Next Steps")
    if all(status.installed for status in statuses):
        ui.message_list([ok_message])
        return
    ui.message_list([fix_message])
    sys.exit(1)


def _render_status(statuses: list[SetupArtifactStatus]) -> None:
    for status in statuses:
        state: ui.State = "ok" if status.installed else "fail"
        ui.row(
            status.label,
            status.target,
            "installed" if status.installed else "missing/stale",
            state=state,
        )
