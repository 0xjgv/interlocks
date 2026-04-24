"""Complexity gate via lizard. Called by stages/ci; not exposed in TASKS."""

from __future__ import annotations

from harness.config import load_config
from harness.runner import Task, run, tool


def task_complexity() -> Task:
    cfg = load_config()
    targets = [cfg.src_dir_arg]
    if cfg.test_dir_arg and cfg.test_dir_arg != cfg.src_dir_arg:
        targets.append(cfg.test_dir_arg)
    return Task(
        "Complexity (lizard)",
        tool(
            "lizard",
            *targets,
            "-C",
            str(cfg.complexity_max_ccn),
            "-a",
            str(cfg.complexity_max_args),
            "-L",
            str(cfg.complexity_max_loc),
            "-i",
            "0",
            "-w",
        ),
        label="complexity",
        display=(
            f"lizard -C {cfg.complexity_max_ccn} "
            f"-a {cfg.complexity_max_args} -L {cfg.complexity_max_loc}"
        ),
    )


def cmd_complexity() -> None:
    run(task_complexity())
