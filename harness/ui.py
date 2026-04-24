"""Shared CLI render primitives: banner, sections, rows, kv blocks, footer.

Single source of truth for `harness` stage output. Stdlib-only. Honors `$NO_COLOR`
and isatty; emits no ANSI under pipes or with colors disabled.
"""

from __future__ import annotations

import os
import shutil
import sys
from typing import TYPE_CHECKING, Literal

from harness import __version__

if TYPE_CHECKING:
    from harness.config import HarnessConfig

State = Literal["ok", "fail", "warn"]

LABEL_WIDTH = 14
_WIDTH_MIN = 60
_WIDTH_MAX = 100

_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def use_color() -> bool:
    """True when ANSI colors should be emitted."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return True
    return sys.stdout.isatty()


def _term_width() -> int:
    """Terminal width clamped to [60, 100]."""
    cols = shutil.get_terminal_size(fallback=(80, 24)).columns
    return max(_WIDTH_MIN, min(_WIDTH_MAX, cols))


def _c(code: str, text: str) -> str:
    if not use_color():
        return text
    return f"{code}{text}{_RESET}"


def banner(cfg: HarnessConfig) -> None:
    """One-line stage banner: `pyharness vX  ·  preset=Y  ·  runner=Z  ·  invoker=W`."""
    preset = cfg.preset or "none"
    parts = [
        f"pyharness v{__version__}",
        f"preset={preset}",
        f"runner={cfg.test_runner}",
        f"invoker={cfg.test_invoker}",
    ]
    print(_c(_DIM, "  ·  ".join(parts)))


def section(name: str) -> None:
    """`── name ─────…` stage/sub-stage header, sized to the terminal."""
    width = _term_width()
    prefix = f"── {name} "
    fill = max(3, width - len(prefix))
    print(f"\n{prefix}{'─' * fill}")


def row(
    label: str,
    command: str,
    status: str,
    *,
    detail: str | None = None,
    state: State = "ok",
) -> None:
    """Three-column task row: `  [label]   command…   status`.

    `detail` (e.g., `"2 files reformatted"`) follows the status after ` · `.
    Long `command` is truncated to fit the available width; status is right-aligned.
    """
    width = _term_width()
    color = _STATE_COLORS[state]
    label_tag = f"[{label}]"
    status_txt = _c(color, status)
    detail_txt = _c(_DIM, detail) if detail else ""
    # Status pinned right; detail (if any) sits left of it with a two-space gap.
    suffix = f"{detail_txt}  {status_txt}" if detail_txt else status_txt
    suffix_len = _plain_len(suffix)
    prefix = f"  {label_tag:<{LABEL_WIDTH}}  "
    used = len(prefix) + len(command) + 2 + suffix_len
    if used <= width:
        padding = " " * (width - len(prefix) - len(command) - suffix_len)
        print(f"{prefix}{command}{padding}{suffix}")
        return
    # Truncate command to fit
    max_cmd = max(10, width - len(prefix) - suffix_len - 3)
    trimmed = command[: max_cmd - 1] + "…" if len(command) > max_cmd else command
    padding = " " * max(1, width - len(prefix) - len(trimmed) - suffix_len)
    print(f"{prefix}{trimmed}{padding}{suffix}")


def kv_block(pairs: list[tuple[str, str]], *, indent: str = "  ", gap: int = 2) -> None:
    """Aligned `key    value` block. Empty `pairs` is a no-op."""
    if not pairs:
        return
    key_width = max(len(k) for k, _ in pairs)
    for key, value in pairs:
        print(f"{indent}{key:<{key_width}}{' ' * gap}{value}")


def stage_footer(elapsed_s: float) -> None:
    """`Completed in X.Ys` footer."""
    print(f"\n{_c(_DIM, f'Completed in {elapsed_s:.1f}s')}")


_STATE_COLORS: dict[State, str] = {
    "ok": _GREEN,
    "fail": _RED,
    "warn": _YELLOW,
}


def _plain_len(text: str) -> int:
    """Length of `text` with ANSI escapes stripped."""
    out = []
    in_esc = False
    for ch in text:
        if ch == "\x1b":
            in_esc = True
            continue
        if in_esc:
            if ch == "m":
                in_esc = False
            continue
        out.append(ch)
    return len(out)
