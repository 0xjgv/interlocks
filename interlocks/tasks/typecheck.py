"""Type-check with basedpyright."""

from __future__ import annotations

from interlocks import ui
from interlocks.config import (
    InterlockConfig,
    load_config,
    project_env_ready,
    project_env_skip_message,
)
from interlocks.defaults_path import config_flag_if_absent
from interlocks.detect import detect_target_interpreter
from interlocks.runner import Task, run, run_task_json, uv_run_with, uvx_tool, warn_skip


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
    venv_python = detect_target_interpreter(cfg.project_root)
    if venv_python is None:
        return []
    return ["--pythonpath", str(venv_python)]


def _typecheck_cmd(cfg: InterlockConfig, targets: list[str]) -> list[str]:
    project_args = _typecheck_project_args(cfg)
    if cfg.test_invoker == "uv":
        return uv_run_with(
            "basedpyright",
            "basedpyright",
            *project_args,
            *targets,
            version=cfg.tool_version("basedpyright"),
        )
    return uvx_tool(
        "basedpyright",
        *project_args,
        *_typecheck_pythonpath_args(cfg),
        *targets,
        version=cfg.tool_version("basedpyright"),
    )


def task_typecheck(files: list[str] | None = None) -> Task | None:
    """Type-check ``files`` (or the src dir) with basedpyright.

    Returns ``None`` (after a ``warn_skip`` advisory) when a non-uv project has
    no in-tree ``.venv``: without ``--pythonpath`` basedpyright cannot resolve
    third-party imports, so its verdict would be installer-dependent.
    """
    cfg = load_config()
    if not project_env_ready(cfg):
        warn_skip(project_env_skip_message("typecheck"))
        return None
    targets = files if files else [cfg.src_dir_arg]
    return Task(
        "Type check",
        _typecheck_cmd(cfg, targets),
        label="typecheck",
        display=f"basedpyright {' '.join(targets)}",
        start_status="running",
    )


def cmd_typecheck() -> None:
    task = task_typecheck()
    if task is None:
        if ui.is_json():
            ui.print_json(
                _typecheck_skip_payload(
                    reason=project_env_skip_message("typecheck"),
                    next_action=(
                        "Create or sync the project environment, then rerun "
                        "`interlocks typecheck`."
                    ),
                )
            )
        return
    if ui.is_json():
        run_task_json("typecheck", task)
        return
    run(task)


def _typecheck_skip_payload(*, reason: str, next_action: str) -> dict[str, object]:
    return {
        "command": "typecheck",
        "passed": True,
        "status": "skipped",
        "reason": reason,
        "next_actions": [next_action],
    }
