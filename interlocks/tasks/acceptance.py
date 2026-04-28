"""Gherkin acceptance tests via pytest-bdd (default) or behave (auto-detected).

Zero-config contract: when no ``features/`` directory exists and no override is
set, ``task_acceptance()`` returns ``None`` and ``cmd_acceptance`` prints a
skip nudge — safe on any foreign repo. Stage wrappers must guard on the same
``None`` signal to stay silent in CI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from interlocks.acceptance_status import (
    AcceptanceStatus,
    classify_acceptance,
    classify_acceptance_with_details,
    remediation_message,
)
from interlocks.acceptance_trace import (
    trace_can_wrap_command,
    trace_enabled,
    trace_wrapper_cmd,
)
from interlocks.behavior_coverage import behavior_registry_for_config
from interlocks.config import InterlockConfig, invoker_prefix, load_config
from interlocks.detect import detect_acceptance_runner
from interlocks.runner import Task, fail_skip, run, warn_skip

if TYPE_CHECKING:
    from pathlib import Path


def task_acceptance() -> Task | None:
    """Build the acceptance Task when the project is RUNNABLE; otherwise None.

    The classifier-driven enforcement decision (fail vs. skip) lives at the
    caller — stages and ``cmd_acceptance`` — so this function neither prints
    nor exits.
    """
    cfg = load_config()
    if classify_acceptance(cfg) is not AcceptanceStatus.RUNNABLE:
        return None
    runner = detect_acceptance_runner(cfg)
    features_dir = cfg.features_dir
    features_arg = cfg.features_dir_arg
    if runner is None or features_dir is None or features_arg is None:
        return None
    if runner == "behave":
        return _maybe_trace_task(cfg, _behave_task(cfg, features_arg))
    return _maybe_trace_task(cfg, _pytest_bdd_task(cfg, features_dir, features_arg))


def cmd_acceptance() -> None:
    cfg = load_config()
    classification = classify_acceptance_with_details(cfg)
    if classification.status is AcceptanceStatus.DISABLED:
        warn_skip("acceptance: disabled via acceptance_runner = 'off'")
        return
    if classification.status is AcceptanceStatus.OPTIONAL_MISSING:
        warn_skip(
            "acceptance: no features/ directory — run `interlocks init-acceptance` to scaffold one"
        )
        return
    if classification.is_required_failure:
        fail_skip(
            remediation_message(
                classification.status,
                classification.features_dir,
                classification.behavior_result,
            )
        )
        return
    task = task_acceptance()
    if task is None:
        warn_skip(
            "acceptance: no features/ directory — run `interlocks init-acceptance` to scaffold one"
        )
        return
    run(task)


def _maybe_trace_task(cfg: InterlockConfig, task: Task) -> Task:
    if not trace_enabled() or not trace_can_wrap_command(task.cmd):
        return task
    symbols = tuple(
        sorted({
            behavior.public_symbol
            for behavior in behavior_registry_for_config(cfg).behaviors
            if behavior.public_symbol is not None
        })
    )
    if not symbols:
        return task
    return Task(
        task.description,
        trace_wrapper_cmd(cfg.project_root, symbols, task.cmd),
        pre_cmds=task.pre_cmds,
        test_summary=task.test_summary,
        allowed_rcs=task.allowed_rcs,
        label=task.label,
        display=task.display,
    )


def _pytest_bdd_task(cfg: InterlockConfig, features_dir: Path, features_arg: str) -> Task:
    # pytest-bdd scenarios live in step-def files (``test_*.py`` with
    # ``scenarios(...)``) — pointing pytest at ``features/`` alone finds nothing.
    # We pass every acceptance path pytest needs to collect; exit 5 ("nothing
    # collected") stays benign for freshly-scaffolded projects.
    targets = _pytest_bdd_targets(cfg, features_dir, features_arg)
    cmd = [*invoker_prefix(cfg), "pytest", *targets, "-q", *cfg.pytest_args]
    return Task(
        "Acceptance (pytest-bdd)",
        cmd,
        test_summary=True,
        allowed_rcs=(0, 5),
        label="acceptance",
        display="pytest-bdd",
    )


def _pytest_bdd_targets(cfg: InterlockConfig, features_dir: Path, features_arg: str) -> list[str]:
    """Directories pytest must collect for pytest-bdd to bind features → steps.

    Canonical scaffold drops step-defs as a sibling of ``features/``; pick that
    up automatically when present so ``interlocks acceptance`` stays self-contained.
    """
    dirs = [features_arg]
    step_defs = features_dir.parent / "step_defs"
    if step_defs.is_dir():
        dirs.append(cfg.relpath(step_defs))
    return dirs


def _behave_task(cfg: InterlockConfig, features_arg: str) -> Task:
    cmd = [*invoker_prefix(cfg), "behave", features_arg]
    return Task("Acceptance (behave)", cmd, label="acceptance", display="behave")
