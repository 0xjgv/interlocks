"""Register interlocks usage in agent-facing markdown (AGENTS.md, CLAUDE.md).

Idempotent: appends a canonical ``<important>`` block to the bottom of each
file only when no existing ``interlocks`` reference is present. Creates the
file if missing. Operates on the current working directory and does not need a
``pyproject.toml`` so it runs in any repo. Stdlib-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from interlocks import ui
from interlocks.defaults_path import path as defaults_path
from interlocks.runner import ok, section, warn_skip
from interlocks.setup_state import AGENT_DOCS, agent_docs_registered, text_references_check_stage

_AGENTS_NEXT_ACTIONS = ("Run `interlocks check` after edits.",)


@dataclass(frozen=True)
class AgentDocResult:
    path: Path
    action: str
    registered: bool


def cmd_agents() -> None:
    section("Register interlocks in agent docs")
    project_root = Path.cwd()
    results = install_agent_docs(project_root)
    if ui.is_json():
        ui.print_json(_agents_payload(project_root, results))
        return
    _render_agent_docs_status(project_root)


def install_agent_docs(project_root: Path | None = None) -> tuple[AgentDocResult, ...]:
    block = defaults_path("agents_block.md").read_text(encoding="utf-8")
    root = project_root or Path.cwd()
    return tuple(_ensure_block(root / name, block) for name in AGENT_DOCS)


def _ensure_block(path: Path, block: str) -> AgentDocResult:
    if not path.exists():
        path.write_text(block, encoding="utf-8")
        ok(f"created {path.name} with interlocks block")
        return AgentDocResult(path=path, action="created", registered=True)
    text = path.read_text(encoding="utf-8")
    if text_references_check_stage(text):
        warn_skip(f"{path.name} already documents interlocks check — skipped")
        return AgentDocResult(path=path, action="kept", registered=True)
    suffix = "" if text.endswith("\n") else "\n"
    path.write_text(f"{text}{suffix}\n{block}", encoding="utf-8")
    ok(f"appended interlocks block to {path.name}")
    return AgentDocResult(path=path, action="appended", registered=True)


def _agents_payload(project_root: Path, results: tuple[AgentDocResult, ...]) -> dict[str, object]:
    registered = all(result.registered for result in results) and agent_docs_registered(
        project_root
    )
    return {
        "command": "agents",
        "passed": True,
        "status": "registered" if registered else "missing/stale",
        "registered": registered,
        "files": [_agent_doc_entry(project_root, result) for result in results],
        "next_actions": list(_AGENTS_NEXT_ACTIONS),
    }


def _agent_doc_entry(project_root: Path, result: AgentDocResult) -> dict[str, object]:
    return {
        "path": _project_relative(project_root, result.path),
        "action": result.action,
        "registered": result.registered,
    }


def _project_relative(project_root: Path, path: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


def _render_agent_docs_status(project_root: Path) -> None:
    registered = agent_docs_registered(project_root)
    state: ui.State = "ok" if registered else "fail"
    ui.row(
        "agent docs",
        "AGENTS.md / CLAUDE.md",
        "registered" if registered else "missing/stale",
        state=state,
        force=True,
    )
