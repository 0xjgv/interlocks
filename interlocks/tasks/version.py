"""Print the installed interlocks version.

Utility command — not a gate. ``task_version`` returns ``None`` to keep the
Task-vs-command distinction honest; ``cmd_version`` prints ``__version__``
straight to stdout.
"""

from __future__ import annotations

from interlocks import __version__, ui


def task_version() -> None:
    return None


def cmd_version() -> None:
    if ui.is_json():
        ui.print_json(_version_payload())
        return
    print(__version__)


def _version_payload(version: str = __version__) -> dict[str, object]:
    return {
        "command": "version",
        "passed": True,
        "version": version,
    }
