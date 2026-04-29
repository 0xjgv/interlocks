"""Install the bundled Claude Code SKILL.md into the consumer repo.

Copies ``interlocks/defaults/skill/SKILL.md`` to
``.claude/skills/interlocks/SKILL.md`` in the current working directory.
Idempotent: a byte-identical copy is a no-op; a divergent copy is overwritten
(the file is tool-managed, not user-edited). Stdlib-only.
"""

from __future__ import annotations

from pathlib import Path

from interlocks.defaults_path import path as defaults_path
from interlocks.runner import ok, section, warn_skip

_DEST = Path(".claude/skills/interlocks/SKILL.md")


def cmd_setup_skill() -> None:
    section("Install Claude Code skill")
    bundled = defaults_path("skill/SKILL.md").read_text(encoding="utf-8")
    dest = Path.cwd() / _DEST
    try:
        existing = dest.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = None
    if existing == bundled:
        warn_skip(f"{_DEST} already installed — skipped")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(bundled, encoding="utf-8")
    ok(f"{'updated' if existing is not None else 'installed'} {_DEST}")
