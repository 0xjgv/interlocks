"""Type-check with basedpyright."""

from __future__ import annotations

from interlocks.config import InterlockConfig, load_config
from interlocks.defaults_path import config_flag_if_absent
from interlocks.detect import detect_target_interpreter
from interlocks.runner import Task, run, uvx_tool


def _typecheck_project_args(cfg: InterlockConfig) -> list[str]:
    """``--project <bundled>`` when the project owns no basedpyright config, else ``[]``."""
    return config_flag_if_absent(
        cfg,
        section="basedpyright",
        filename="pyrightconfig.json",
        flag="--project",
        sidecars=("pyrightconfig.json", "pyrightconfig.toml"),
    )


def _typecheck_pythonpath_args(cfg: InterlockConfig) -> list[str]:
    """Point basedpyright at the target venv interpreter when one is concrete."""
    if cfg.test_invoker == "uv":
        return []
    venv_python = detect_target_interpreter(cfg.project_root)
    if venv_python is None:
        return []
    return ["--pythonpath", str(venv_python)]


def task_typecheck(files: list[str] | None = None) -> Task:
    cfg = load_config()
    targets = files if files else [cfg.src_dir_arg]
    return Task(
        "Type check",
        uvx_tool(
            "basedpyright",
            *_typecheck_project_args(cfg),
            *_typecheck_pythonpath_args(cfg),
            *targets,
            version=cfg.tool_version("basedpyright"),
        ),
        label="typecheck",
        display=f"basedpyright {' '.join(targets)}",
    )


def cmd_typecheck() -> None:
    run(task_typecheck())
