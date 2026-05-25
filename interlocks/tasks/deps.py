"""Dependency hygiene via deptry — unused/missing/transitive/misplaced imports."""

from __future__ import annotations

import re

from interlocks import ui
from interlocks.config import InterlockConfig, load_config
from interlocks.runner import Task, run, run_task_json, uvx_tool


def task_deps() -> Task:
    return Task(
        "Deps (deptry)",
        _deptry_cmd(load_config()),
        label="deps",
        display="deptry",
        start_status="running",
    )


def _deptry_cmd(cfg: InterlockConfig) -> list[str]:
    # No bundled-config fallback: deptry's `--config` doubles as the project-manifest
    # pointer (for dep discovery), so pointing it at a shared default breaks detection.
    # Deptry's built-in defaults apply automatically when the project has no [tool.deptry].
    return uvx_tool(
        "deptry",
        cfg.src_dir_arg,
        *_property_exclude_args(cfg),
        "--known-first-party",
        cfg.src_dir.name,
        version=cfg.tool_version("deptry"),
    )


def _property_exclude_args(cfg: InterlockConfig) -> list[str]:
    properties_dir = cfg.properties_dir or (cfg.project_root / "properties")
    if not properties_dir.is_relative_to(cfg.src_dir):
        return []
    relpath = cfg.relpath(properties_dir)
    if relpath in ("", "."):
        return []
    return ["--extend-exclude", re.escape(relpath)]


def cmd_deps() -> None:
    if ui.is_json():
        run_task_json("deps", task_deps())
        return
    run(task_deps())
