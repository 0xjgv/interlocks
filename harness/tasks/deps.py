"""Dependency hygiene via deptry — unused/missing/transitive/misplaced imports."""

from __future__ import annotations

from harness.config import HarnessConfig, load_config
from harness.runner import Task, run, tool


def task_deps() -> Task:
    return Task("Deps (deptry)", _deptry_cmd(load_config()))


def _deptry_cmd(cfg: HarnessConfig) -> list[str]:
    # No bundled-config fallback: deptry's `--config` doubles as the project-manifest
    # pointer (for dep discovery), so pointing it at a shared default breaks detection.
    # Deptry's built-in defaults apply automatically when the project has no [tool.deptry].
    return tool("deptry", cfg.src_dir_arg, "--known-first-party", cfg.src_dir.name)


def cmd_deps() -> None:
    run(task_deps())
