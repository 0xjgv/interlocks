"""CI stage."""

from __future__ import annotations

import json
import os
import time

from interlocks import run_summary, ui
from interlocks.acceptance_status import (
    AcceptanceStatus,
    acceptance_failure_task,
    classify_acceptance_with_details,
)
from interlocks.config import InterlockConfig, MutationCIMode, load_config
from interlocks.runner import Task, run_tasks
from interlocks.skip import (
    SkipPolicy,
    current_skip_policy,
    maybe_print_skip_banner,
    run_unless_skipped,
    warn_skipped,
)
from interlocks.tasks.acceptance import task_acceptance_with_attribution
from interlocks.tasks.arch import task_arch
from interlocks.tasks.audit import task_audit
from interlocks.tasks.behavior_attribution import cmd_behavior_attribution
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
    run_summary.reset()
    context = os.environ.get("INTERLOCKS_CI_CONTEXT")
    if context:
        run_summary.record_context(context)
    skip_policy = current_skip_policy()
    ui.banner(cfg)
    maybe_print_skip_banner(skip_policy)
    ui.section("CI Checks")
    # DISABLED + OPTIONAL_MISSING → skip silently (preserve current CI behavior)
    exit_code = 0
    try:
        run_tasks(_parallel_tasks(cfg))
        # CRAP/mutation read coverage.xml produced by task_coverage — keep sequential.
        ui.section("Gates")
        _post_coverage_gates(cfg, skip_policy)
    except SystemExit as exc:
        exit_code = int(exc.code) if isinstance(exc.code, int) else 1
        raise
    finally:
        elapsed = time.monotonic() - start
        _write_ci_evidence(cfg, elapsed_seconds=elapsed, passed=exit_code == 0, context=context)
        run_summary.flush(cfg)
    ui.stage_footer(elapsed)


def _parallel_tasks(cfg: InterlockConfig) -> list[Task]:
    tasks: list[Task] = [
        task_format_check(),
        task_lint(),
        task_complexity(),
        task_audit(),
        task_deps(),
        task_typecheck(),
        task_coverage(),
    ]
    optional = (task_arch(), _acceptance_task(cfg))
    tasks.extend(t for t in optional if t is not None)
    return tasks


def _acceptance_task(cfg: InterlockConfig) -> Task | None:
    acceptance = classify_acceptance_with_details(cfg)
    if acceptance.is_required_failure:
        return acceptance_failure_task(acceptance)
    if acceptance.status is AcceptanceStatus.RUNNABLE:
        return task_acceptance_with_attribution(cfg)
    return None


def _post_coverage_gates(cfg: InterlockConfig, skip_policy: SkipPolicy) -> None:
    if skip_policy.enabled("coverage"):
        warn_skipped("crap", "coverage was skipped")
    else:
        run_unless_skipped("crap", cmd_crap, skip_policy)
    run_unless_skipped("attribution", lambda: cmd_behavior_attribution(refresh=False), skip_policy)
    if _should_run_mutation(cfg.mutation_ci_mode, run_in_ci=cfg.run_mutation_in_ci):
        run_unless_skipped(
            "mutation",
            lambda: cmd_mutation(changed_only=cfg.mutation_ci_mode == "incremental"),
            skip_policy,
        )


def _should_run_mutation(mode: MutationCIMode, *, run_in_ci: bool) -> bool:
    """Back-compat: when no mode is set, fall back to legacy ``run_mutation_in_ci``."""
    return mode != "off" or run_in_ci


def _write_ci_evidence(
    cfg: InterlockConfig,
    *,
    elapsed_seconds: float,
    passed: bool,
    created_at: float | None = None,
    context: str | None = None,
) -> None:
    path = cfg.ci_evidence_path
    payload: dict[str, object] = {
        "command": "interlocks ci",
        "elapsed_seconds": round(elapsed_seconds, 3),
        "created_at": created_at if created_at is not None else time.time(),
        "passed": passed,
        "budget_seconds": cfg.pr_ci_runtime_budget_seconds,
    }
    if context:
        payload["context"] = context
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
