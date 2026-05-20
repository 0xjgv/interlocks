"""Run tests.

Zero-config contract: when no test directory exists (greenfield project),
``task_test()`` returns ``None`` and ``cmd_test`` prints a skip nudge — stage
wrappers guard on the same ``None`` signal. Mirrors ``interlocks.tasks.acceptance``.

``cmd_test`` additionally checks project-env readiness *before* calling
``task_test()``: a non-uv project with no ``.venv`` is skipped with its own
nudge, so the env nudge and the no-test-dir nudge never collide.
"""

from __future__ import annotations

from interlocks.config import (
    build_test_command,
    load_config,
    project_env_ready,
    project_env_skip_message,
)
from interlocks.runner import Task, run, warn_skip


def task_test() -> Task | None:
    cfg = load_config()
    if not cfg.test_dir.is_dir():
        return None
    return Task(
        "Run tests",
        build_test_command(cfg),
        test_summary=True,
        label="test",
        display=f"{cfg.test_runner} {cfg.test_dir_arg}",
    )


def cmd_test() -> None:
    cfg = load_config()
    if not project_env_ready(cfg):
        warn_skip(project_env_skip_message("test"))
        return
    task = task_test()
    if task is None:
        warn_skip("test: no test dir detected — run `interlocks init` to scaffold tests/")
        return
    run(task)
