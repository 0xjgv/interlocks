"""Interactive consent prompt for crash issue reporting."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Literal, TextIO

if TYPE_CHECKING:
    from pathlib import Path

CrashReportDecision = Literal["report", "skip", "unavailable"]

_PROMPT = "Report this crash to the interlocks maintainers? Y/n: "


def prompt_for_report(
    *,
    stdin: TextIO = sys.stdin,
    stderr: TextIO = sys.stderr,
    local_path: Path | None = None,
) -> CrashReportDecision:
    """Ask whether to open a pre-filled GitHub issue for a captured crash.

    Non-interactive invocations never prompt or report. Invalid answers are
    treated as a skip so the crash path never traps the user in a retry loop.
    """
    if not stdin.isatty() or not stderr.isatty():
        return "unavailable"

    print("interlocks hit an internal bug and saved a crash report.", file=stderr)
    if local_path is not None:
        print(f"Local crash file: {local_path}", file=stderr)
    stderr.write(_PROMPT)
    stderr.flush()

    try:
        response = stdin.readline()
    except (EOFError, OSError):
        return "unavailable"
    if not response:
        return "unavailable"

    normalized = response.strip().lower()
    if normalized in ("", "y", "yes"):
        return "report"
    if normalized in ("n", "no"):
        print("Crash report skipped.", file=stderr)
        return "skip"

    print("Crash report skipped: unrecognized response.", file=stderr)
    return "skip"
