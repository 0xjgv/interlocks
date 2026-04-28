"""CI stage."""

from __future__ import annotations

import json
import time

from interlocks import ui
from interlocks.acceptance_status import (
    AcceptanceStatus,
    acceptance_failure_task,
    classify_acceptance_with_details,
)
from interlocks.config import InterlockConfig, MutationCIMode, load_config
from interlocks.runner import run_tasks
from interlocks.tasks.acceptance import task_acceptance
from interlocks.tasks.arch import task_arch
from interlocks.tasks.audit import task_audit
from interlocks.tasks.complexity import task_complexity
from interlocks.tasks.coverage import task_coverage
from interlocks.tasks.crap import cmd_crap
from interlocks.tasks.deps import task_deps
from interlocks.tasks.format_check import task_format_check
from interlocks.tasks.lint import task_lint
from interlocks.tasks.mutation import cmd_mutation
from interlocks.tasks.typecheck import task_typecheck


def cmd_ci() -> None:
    """Full verification: format_check, lint, complexity, audit, deps, arch, typecheck,
    coverage, CRAP, (optionally) mutation."""
    start = time.monotonic()
    cfg = load_config()
    ui.banner(cfg)
    ui.section("CI Checks")
    tasks = [
        task_format_check(),
        task_lint(),
        task_complexity(),
        task_audit(allow_network_skip=True),
        task_deps(),
        task_typecheck(),
        task_coverage(),
    ]
    arch = task_arch()
    if arch is not None:
        tasks.append(arch)
    acceptance = classify_acceptance_with_details(cfg)
    if acceptance.is_required_failure:
        tasks.append(acceptance_failure_task(acceptance))
    elif acceptance.status is AcceptanceStatus.RUNNABLE:
        acceptance_task = task_acceptance()
        if acceptance_task is not None:
            tasks.append(acceptance_task)
    # DISABLED + OPTIONAL_MISSING → skip silently (preserve current CI behavior)
    exit_code = 0
    try:
        run_tasks(tasks)
        # CRAP/mutation read coverage.xml produced by task_coverage — keep sequential.
        ui.section("Gates")
        cmd_crap()
        if _should_run_mutation(cfg.mutation_ci_mode, run_in_ci=cfg.run_mutation_in_ci):
            cmd_mutation(changed_only=cfg.mutation_ci_mode == "incremental")
    except SystemExit as exc:
        exit_code = int(exc.code) if isinstance(exc.code, int) else 1
        raise
    finally:
        elapsed = time.monotonic() - start
        _write_ci_evidence(cfg, elapsed_seconds=elapsed, passed=exit_code == 0)
    ui.stage_footer(elapsed)


def _should_run_mutation(mode: MutationCIMode, *, run_in_ci: bool) -> bool:
    """Back-compat: when no mode is set, fall back to legacy ``run_mutation_in_ci``."""
    return mode != "off" or run_in_ci


def _write_ci_evidence(
    cfg: InterlockConfig,
    *,
    elapsed_seconds: float,
    passed: bool,
    created_at: float | None = None,
) -> None:
    path = cfg.ci_evidence_path
    payload = {
        "command": "interlocks ci",
        "elapsed_seconds": round(elapsed_seconds, 3),
        "created_at": created_at if created_at is not None else time.time(),
        "passed": passed,
        "budget_seconds": cfg.pr_ci_runtime_budget_seconds,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
