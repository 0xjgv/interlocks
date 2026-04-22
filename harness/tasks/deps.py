"""Dependency hygiene via deptry — unused/missing/transitive/misplaced imports."""

from __future__ import annotations

from harness.config import HarnessConfig, load_config
from harness.runner import Task, run, tool


def task_deps() -> Task:
    """Scan ``src_dir`` for unused/missing/transitive deps.

    Auto-passes ``--known-first-party`` derived from ``src_dir`` so intra-project
    imports aren't flagged as transitive when the package name differs from the
    project name in ``pyproject.toml``. Per-project overrides go under ``[tool.deptry]``.
    """
    cfg = load_config()
    return Task("Deps (deptry)", _deptry_cmd(cfg))


def _deptry_cmd(cfg: HarnessConfig) -> list[str]:
    return tool("deptry", cfg.src_dir_arg, "--known-first-party", cfg.src_dir.name)


def cmd_deps() -> None:
    run(task_deps())
