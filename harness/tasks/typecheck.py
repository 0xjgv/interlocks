"""Type-check with basedpyright."""

from __future__ import annotations

from harness.config import load_config
from harness.defaults_path import config_flag_if_absent
from harness.runner import Task, run, tool


def _typecheck_project_args() -> list[str]:
    """``--project <bundled>`` when the project owns no basedpyright config, else ``[]``."""
    return config_flag_if_absent(
        load_config(),
        section="basedpyright",
        filename="pyrightconfig.json",
        flag="--project",
        sidecars=("pyrightconfig.json", "pyrightconfig.toml"),
    )


def task_typecheck() -> Task:
    cfg = load_config()
    return Task(
        "Type check",
        tool("basedpyright", *_typecheck_project_args(), cfg.src_dir_arg),
        label="typecheck",
        display=f"basedpyright {cfg.src_dir_arg}",
    )


def cmd_typecheck() -> None:
    run(task_typecheck())
