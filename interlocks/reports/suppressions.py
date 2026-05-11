"""Suppressions scanner and report. Stdlib-only."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from interlocks import ui
from interlocks.config import load_config

if TYPE_CHECKING:
    from collections.abc import Iterable

_SUPPRESSION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("noqa", re.compile(r"#\s*noqa(?::\s*([A-Z][A-Z0-9]+(?:\s*,\s*[A-Z][A-Z0-9]+)*))?")),
    (
        "type_ignore",
        re.compile(r"#\s*type:\s*ignore(?:\[([a-zA-Z0-9_-]+(?:\s*,\s*[a-zA-Z0-9_-]+)*)\])?"),
    ),
    (
        "pyright_ignore",
        re.compile(r"#\s*pyright:\s*ignore(?:\[([a-zA-Z0-9_-]+(?:\s*,\s*[a-zA-Z0-9_-]+)*)\])?"),
    ),
]


def _parse_line_for_suppressions(line: str) -> list[tuple[str, list[str]]]:
    """Return all (kind, rules) matches found on a single line."""
    matches: list[tuple[str, list[str]]] = []
    for kind, pat in _SUPPRESSION_PATTERNS:
        m = pat.search(line)
        if m:
            rules = [r.strip() for r in m.group(1).split(",") if r.strip()] if m.group(1) else []
            matches.append((kind, rules))
    return matches


def _scan_suppressions(roots: Iterable[str] | None = None) -> dict[str, list[list[str]]]:
    """Scan Python files for suppression comments. Returns {kind: [rules...]}."""
    if roots is None:
        cfg = load_config()
        roots = (cfg.src_dir_arg, cfg.test_dir_arg)
    results: dict[str, list[list[str]]] = {}
    for dir_name in roots:
        for py_file in sorted(Path(dir_name).rglob("*.py")):
            try:
                text = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line in text.splitlines():
                for kind, rules in _parse_line_for_suppressions(line):
                    results.setdefault(kind, []).append(rules)
    return results


def print_suppressions_report() -> None:
    """Print a report-only summary of suppressions found in source (verbose only).

    Suppression counts are advisory background data, not blocking output. They
    don't belong on the agent-default surface; pass ``--verbose`` to see them.
    """
    if not ui.is_verbose():
        return
    results = _scan_suppressions()
    total = sum(len(v) for v in results.values())
    ui.section("Suppressions")
    print(f"Suppressions: {total} total")
    if total == 0:
        return
    for kind, entries in sorted(results.items()):
        print(f"  {kind}: {len(entries)}")
        rule_counts: Counter[str] = Counter()
        for rules in entries:
            rule_counts.update(rules)
        for rule, count in sorted(rule_counts.items(), key=lambda x: (-x[1], x[0]))[:10]:
            print(f"    {rule}: {count}")
