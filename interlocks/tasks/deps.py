"""Dependency hygiene via deptry — unused/missing/transitive/misplaced imports."""

from __future__ import annotations

from interlocks.config import InterlockConfig, load_config
from interlocks.runner import Task, run, uvx_tool


def task_deps() -> Task:
    return Task(
        "Deps (deptry)",
        _deptry_cmd(load_config()),
        label="deps",
        display="deptry",
    )


def _deptry_cmd(cfg: InterlockConfig) -> list[str]:
    # No bundled-config fallback: deptry's `--config` doubles as the project-manifest
    # pointer (for dep discovery), so pointing it at a shared default breaks detection.
    # Deptry's built-in defaults apply automatically when the project has no [tool.deptry].
    return uvx_tool(
        "deptry",
        cfg.src_dir_arg,
        "--known-first-party",
        cfg.src_dir.name,
        version=cfg.tool_version("deptry"),
    )


def cmd_deps() -> None:
    run(task_deps())
