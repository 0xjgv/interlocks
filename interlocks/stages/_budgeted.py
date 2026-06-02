"""Shared budgeted-mutation glue used by ``check``, ``pre-commit``, and ``post-edit``.

Stages default to the ``dynamic`` budget (small, predictable mutations);
``interlocks fix optimize`` invoked from the CLI keeps its own ``unblock``
default. ``--renovate`` and ``--mutation-budget=<name>`` override.

``fix`` and ``format`` are one budgeted lint/format mutation: skipping either
label disables the whole gate.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from interlocks import ui
from interlocks.runner import arg_flag_value, arg_value, record_result
from interlocks.skip import current_skip_policy, warn_skipped
from interlocks.tasks.fix_optimize import cmd_fix_optimize

if TYPE_CHECKING:
    from interlocks.skip import SkipPolicy

_ROW_COMMAND = "budgeted ruff lint/format mutation"


def run_budgeted_mutation(
    *, base: str, emit_legacy_rows: bool, skip_policy: SkipPolicy | None = None
) -> None:
    """Resolve the stage budget and invoke ``fix-optimize`` with ``--apply``.

    ``emit_legacy_rows`` writes the ``fix`` + ``format`` rows that pre-budget
    stages used to emit; ``post-edit`` skips them because it has no stage table.

    ``fix`` and ``format`` are aliases for this single gate — skipping either
    label disables the mutation entirely. ``skip_policy`` defaults to the shared
    :func:`current_skip_policy` so an advisory caller (``post-edit``) still
    honors ``INTERLOCKS_SKIP`` / config ``skip``.
    """
    policy = skip_policy or current_skip_policy()
    if policy.enabled("fix") or policy.enabled("format"):
        warn_skipped("fix", _ROW_COMMAND)
        return
    budget = "renovation" if arg_flag_value("--renovate", "1") is not None else "dynamic"
    cli_budget = arg_value("--mutation-budget=", "")
    if cli_budget:
        budget = cli_budget
    try:
        # `verify_cmd=(sys.executable, "-c", "pass")` is a deliberate no-op: the stage
        # runs its own typecheck + test gates right after this mutation, so they
        # are the real verification — a heavier verifier here would be slow and,
        # for `check`, recursive. `apply_*_with_verify`'s restore-on-failure
        # still guards the one case the no-op cannot catch: ruff returning rc ≥ 2.
        cmd_fix_optimize(
            base=base,
            budget=budget,
            apply=True,
            stats_path="",
            verify_cmd=(sys.executable, "-c", "pass"),
        )
    except SystemExit as exc:
        # `cmd_fix_optimize` exits non-zero when ruff itself fails (rc ≥ 2).
        # Record the failed verdict before re-raising so `print_stage_verdict`
        # cannot report `ok` for a stage that exits non-zero.
        if emit_legacy_rows and exc.code not in (0, None):
            _emit_legacy_rows("fail", detail=f"budgeted mutation exited {exc.code}")
        raise
    if emit_legacy_rows:
        _emit_legacy_rows("ok", detail=None)


def _emit_legacy_rows(state: ui.State, *, detail: str | None) -> None:
    """Write the ``fix`` + ``format`` stage rows for one budgeted mutation.

    The mutation is a single gate; the duplicate ``format`` row keeps existing
    ``skip = ["format"]`` configs and the stage verdict legible.
    """
    status = "ok" if state == "ok" else "failed"
    for label in ("fix", "format"):
        ui.gate_row(label, _ROW_COMMAND, status, state=state)
        record_result(label, status=state, elapsed=None, detail=detail)
