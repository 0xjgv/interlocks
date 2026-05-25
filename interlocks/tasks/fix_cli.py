"""Shared CLI parsing helpers for lintfix commands."""

from __future__ import annotations

import shlex
import sys

from interlocks.runner import arg_value

DEFAULT_VERIFY_CMD: tuple[str, ...] = ("interlocks", "ci")


def verify_cmd_from_argv(command: str) -> tuple[str, ...]:
    raw = arg_value("--verify-cmd=", "")
    if not raw:
        return DEFAULT_VERIFY_CMD
    try:
        return tuple(shlex.split(raw))
    except ValueError as exc:
        print(f"interlocks {command}: invalid --verify-cmd: {exc}", file=sys.stderr)
        sys.exit(2)
