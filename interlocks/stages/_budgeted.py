"""Shared budgeted-mutation glue used by ``check``, ``pre-commit``, and ``post-edit``.

Stages default to the ``dynamic`` budget (small, predictable mutations);
``interlocks fix-optimize`` invoked from the CLI keeps its own ``unblock``
default. ``--renovate`` and ``--mutation-budget=<name>`` override.
"""

from __future__ import annotations

from interlocks import ui
from interlocks.runner import arg_flag_value, arg_value, record_result
from interlocks.tasks.fix_optimize import cmd_fix_optimize


def run_budgeted_mutation(*, base: str, emit_legacy_rows: bool) -> None:
    """Resolve the stage budget and invoke ``fix-optimize`` with ``--apply``.

    ``emit_legacy_rows`` writes the ``fix`` + ``format`` rows that pre-budget
    stages used to emit; ``post-edit`` skips them because it has no stage table.
    """
    budget = "renovation" if arg_flag_value("--renovate", "1") is not None else "dynamic"
    cli_budget = arg_value("--mutation-budget=", "")
    if cli_budget:
        budget = cli_budget
    cmd_fix_optimize(
        base=base,
        budget=budget,
        apply=True,
        stats_path="",
        verify_cmd=("python", "-c", "pass"),
    )
    if emit_legacy_rows:
        ui.row("fix", "budgeted ruff lint/format mutation", "ok")
        ui.row("format", "budgeted ruff lint/format mutation", "ok")
        record_result("fix", status="ok", elapsed=None, detail=None)
        record_result("format", status="ok", elapsed=None, detail=None)
