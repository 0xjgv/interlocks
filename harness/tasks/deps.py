"""Dependency hygiene via deptry — unused/missing/transitive/misplaced imports."""

from __future__ import annotations

from harness.config import HarnessConfig, load_config
from harness.runner import Task, run, tool


def task_deps() -> Task:
    return Task("Deps (deptry)", _deptry_cmd(load_config()))


def _deptry_cmd(cfg: HarnessConfig) -> list[str]:
    # --known-first-party: derive from src_dir so intra-project imports aren't flagged
    # as transitive when the package name differs from [project].name in pyproject.
    return tool("deptry", cfg.src_dir_arg, "--known-first-party", cfg.src_dir.name)


def cmd_deps() -> None:
    run(task_deps())
