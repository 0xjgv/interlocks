"""`interlocks explain [--all | <command>]` — render the CLI contract as prose.

Read-only. With no argument, prints a grouped one-row-per-command index. With
`--all`, walks the full command catalog and prints a prose block per
command. With one command name (aliases resolved), prints just that block.
Backed by the :data:`COMMAND_DOCS` registry in :mod:`interlocks.command_docs`;
rendering lives here, data lives there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from interlocks import ui
from interlocks.command_docs import (
    ALIASES,
    COMMAND_DOCS_BY_NAME,
    COMMAND_GROUPS,
    CommandDoc,
    alias_suffix,
    command_doc_payload,
    command_index_payload,
    command_mutation_summary,
    command_usage,
)
from interlocks.runner import fail_skip, subcommand_args

if TYPE_CHECKING:
    from collections.abc import Iterator


def cmd_explain() -> None:
    want_all, positional = _parse_explain_args()
    if ui.is_json():
        ui.print_json(_explain_payload(want_all=want_all, positional=positional))
        return
    if not positional:
        _explain_all() if want_all else _explain_index()
        return
    doc = _resolve_doc(positional[0])
    for line in render_command_doc(doc):
        print(line)


def _parse_explain_args() -> tuple[bool, list[str]]:
    args = subcommand_args("explain")
    flags = [arg for arg in args if arg.startswith("-")]
    bad = [arg for arg in flags if arg not in {"--all", "--json"}]
    if bad:
        fail_skip(f"explain: unexpected option: {bad[0]}")
    positional = [arg for arg in args if not arg.startswith("-")]
    if len(positional) > 1:
        fail_skip("explain: accepts at most one command name")
    return "--all" in flags, positional


def _resolve_doc(requested: str) -> CommandDoc:
    name = ALIASES.get(requested, requested)
    doc = COMMAND_DOCS_BY_NAME.get(name)
    if doc is None:
        fail_skip(f"explain: unknown command: {requested}")
    return doc


def _command_docs_by_group() -> Iterator[tuple[str, str, CommandDoc | None]]:
    """Yield `(group_name, command_name, doc)` over the full command catalog.

    `doc` is `None` only if the registry drifted out of sync with
    `COMMAND_GROUPS` — the drift guard keeps that unreachable, but callers
    degrade gracefully.
    """
    for group_name, names in COMMAND_GROUPS:
        for name in names:
            yield group_name, name, COMMAND_DOCS_BY_NAME.get(name)


def _explain_payload(*, want_all: bool, positional: list[str]) -> dict[str, object]:
    if positional:
        return command_doc_payload(_resolve_doc(positional[0]))
    return {
        "command": "explain",
        "mode": "all" if want_all else "index",
        "groups": _explain_groups_payload(full=want_all),
    }


def _explain_groups_payload(*, full: bool) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    current_group: str | None = None
    current_commands: list[dict[str, object]] = []
    for group_name, name, doc in _command_docs_by_group():
        if current_group != group_name:
            current_group = group_name
            current_commands = []
            groups.append({"name": group_name, "commands": current_commands})
        current_commands.append(_explain_command_payload(name, doc, full=full))
    return groups


def _explain_command_payload(
    name: str, doc: CommandDoc | None, *, full: bool
) -> dict[str, object]:
    if doc is None:
        return {"name": name, "summary": "(no explanation registered)", "aliases": []}
    return command_doc_payload(doc) if full else command_index_payload(doc)


def _explain_index() -> None:
    """Grouped one-row-per-command index — the default-mode `explain` surface."""
    last_group = None
    for group_name, name, doc in _command_docs_by_group():
        if group_name != last_group:
            ui.group_header(group_name)
            last_group = group_name
        if doc is None:
            print(f"  [{name}]  (no explanation registered)")
        else:
            print(render_command_doc(doc)[0])
    print()
    print(
        "Run `interlocks explain <cmd>` for one command's full block, "
        "or `interlocks explain --all` for all."
    )


def _explain_all() -> None:
    """Full per-command prose dump grouped by `section` header — the `--all` surface."""
    last_group = None
    first = True
    for group_name, name, doc in _command_docs_by_group():
        if group_name != last_group:
            ui.section(group_name)
            last_group = group_name
        if doc is None:
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
        f"    Usage:      interlocks {command_usage(doc)}",
        f"    When to use: {doc.when_to_use}",
        f"    Mutates:     {command_mutation_summary(doc)}",
        f"    Outputs:     {outputs}",
        f"    Exit codes:  {exit_codes}",
    ]
