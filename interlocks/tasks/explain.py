"""`interlocks explain [<command>]` — render the CLI contract as prose.

Read-only. With no argument, walks the full command catalog and prints a prose
block per command. With one command name (aliases resolved), prints just that
block. Backed by the :data:`COMMAND_DOCS` registry in
:mod:`interlocks.command_docs`; rendering lives here, data lives there.
"""

from __future__ import annotations

from interlocks import ui
from interlocks.command_docs import ALIASES, COMMAND_DOCS_BY_NAME, CommandDoc, alias_suffix
from interlocks.runner import fail_skip, subcommand_args


def cmd_explain() -> None:
    args = subcommand_args("explain")
    flags = [arg for arg in args if arg.startswith("-")]
    if flags:
        fail_skip(f"explain: unexpected option: {flags[0]}")
    positional = [arg for arg in args if not arg.startswith("-")]
    if len(positional) > 1:
        fail_skip("explain: accepts at most one command name")
    if not positional:
        _explain_all()
        return
    requested = positional[0]
    name = ALIASES.get(requested, requested)
    doc = COMMAND_DOCS_BY_NAME.get(name)
    if doc is None:
        fail_skip(f"explain: unknown command: {requested}")
    for line in render_command_doc(doc):
        print(line)


def _explain_all() -> None:
    # Lazy import — `cli` imports this module, so a top-level import would cycle.
    from interlocks.cli import TASK_GROUPS  # noqa: PLC0415

    first = True
    for group_name, group in TASK_GROUPS:
        ui.section(group_name)
        for name in group:
            doc = COMMAND_DOCS_BY_NAME.get(name)
            if doc is None:
                # Should be unreachable — the drift guard keeps the registry
                # complete — but degrade gracefully rather than KeyError.
                print(f"  [{name}]  (no explanation registered)")
                continue
            if not first:
                print()
            first = False
            for line in render_command_doc(doc):
                print(line)


def render_command_doc(doc: CommandDoc) -> list[str]:
    """Render one :class:`CommandDoc` as a prose block (list of output lines)."""
    outputs = ", ".join(doc.outputs) if doc.outputs else "(none)"
    exit_codes = "; ".join(f"{code} = {meaning}" for code, meaning in doc.exit_codes)
    return [
        f"  [{doc.name}]  {doc.summary}{alias_suffix(doc.name)}",
        f"    When to use: {doc.when_to_use}",
        f"    Mutates:     {'yes' if doc.mutates else 'no'}",
        f"    Outputs:     {outputs}",
        f"    Exit codes:  {exit_codes}",
    ]
