"""Run tests.

Zero-config contract: when no test directory exists (greenfield project),
``task_test()`` returns ``None`` and ``cmd_test`` prints a skip nudge — stage
wrappers guard on the same ``None`` signal. Mirrors ``harness.tasks.acceptance``.
"""

from __future__ import annotations

from harness.config import build_test_command, load_config
from harness.runner import Task, run, warn_skip


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
    task = task_test()
    if task is None:
        warn_skip("test: no test dir detected — run `harness init` to scaffold tests/")
        return
    run(task)
