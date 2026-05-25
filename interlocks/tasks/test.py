"""Run tests.

Zero-config contract: when no test directory exists (greenfield project),
``task_test()`` returns ``None`` and ``cmd_test`` prints a skip nudge — stage
wrappers guard on the same ``None`` signal. Mirrors ``interlocks.tasks.acceptance``.

``cmd_test`` additionally checks project-env readiness *before* calling
``task_test()``: a non-uv project with no ``.venv`` is skipped with its own
nudge, so the env nudge and the no-test-dir nudge never collide.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from interlocks import ui
from interlocks.config import (
    build_test_command,
    load_config,
    project_env_ready,
    project_env_skip_message,
)
from interlocks.runner import Task, run, run_task_json, warn_skip

if TYPE_CHECKING:
    from collections.abc import Sequence


def task_test(*, extra_pytest_args: Sequence[str] = ()) -> Task | None:
    cfg = load_config()
    if not cfg.test_dir.is_dir():
        return None
    cmd = build_test_command(cfg)
    if cfg.test_runner == "pytest" and extra_pytest_args:
        cmd = [*cmd, *extra_pytest_args]
    return Task(
        "Run tests",
        cmd,
        test_summary=True,
        label="test",
        display=f"{cfg.test_runner} {cfg.test_dir_arg}",
        start_status="running",
    )


def cmd_test() -> None:
    cfg = load_config()
    if not project_env_ready(cfg):
        if ui.is_json():
            ui.print_json(
                _test_skip_payload(
                    reason=project_env_skip_message("test"),
                    next_action=(
                        "Create or sync the project environment, then rerun `interlocks test`."
                    ),
                )
            )
            return
        warn_skip(project_env_skip_message("test"))
        return
    task = task_test()
    if task is None:
        if ui.is_json():
            ui.print_json(
                _test_skip_payload(
                    reason="no test dir detected",
                    next_action="Run `interlocks init` to scaffold tests/.",
                )
            )
            return
        warn_skip("test: no test dir detected — run `interlocks init` to scaffold tests/")
        return
    if ui.is_json():
        run_task_json("test", task)
        return
    run(task)


def _test_skip_payload(*, reason: str, next_action: str) -> dict[str, object]:
    return {
        "command": "test",
        "passed": True,
        "status": "skipped",
        "reason": reason,
        "next_actions": [next_action],
    }
