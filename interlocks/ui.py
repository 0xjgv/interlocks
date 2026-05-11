"""Shared CLI render primitives: banner, sections, rows, kv blocks, footer.

Single source of truth for `interlocks` stage output. Stdlib-only. Honors `$NO_COLOR`
and isatty; emits no ANSI under pipes or with colors disabled.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from typing import TYPE_CHECKING, Literal

from interlocks import __version__

if TYPE_CHECKING:
    from interlocks.config import InterlockConfig

State = Literal["ok", "fail", "warn"]

LABEL_WIDTH = 12
_WIDTH_MIN = 50
_WIDTH_MAX = 65

_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_DIM = "\033[2m"
_RESET = "\033[0m"

_STATE_COLORS: dict[State, str] = {
    "ok": _GREEN,
    "fail": _RED,
    "warn": _YELLOW,
}


def use_color() -> bool:
    """True when ANSI colors should be emitted."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return True
    return sys.stdout.isatty()


def is_verbose() -> bool:
    """True when `--verbose` requested; gates all chrome (banners, sections, ok-rows, footers)."""
    return "--verbose" in sys.argv


def _term_width() -> int:
    """Terminal width clamped to [50, 65]."""
    cols = shutil.get_terminal_size(fallback=(80, 24)).columns
    return max(_WIDTH_MIN, min(_WIDTH_MAX, cols))


def _c(code: str, text: str) -> str:
    if not use_color():
        return text
    return f"{code}{text}{_RESET}"


def banner(cfg: InterlockConfig) -> None:
    """One-line stage banner: `interlocks vX · preset=Y · runner=Z · invoker=W`."""
    if not is_verbose():
        return
    preset = cfg.preset or "none"
    parts = [
        f"interlocks v{__version__}",
        f"preset={preset}",
        f"runner={cfg.test_runner}",
        f"invoker={cfg.test_invoker}",
    ]
    print(_c(_DIM, " · ".join(parts)))


def command_banner(command: str, cfg: InterlockConfig | None = None) -> None:
    """One-line command banner aligned with stage banners."""
    if not is_verbose():
        return
    parts = [f"interlocks v{__version__}", f"command={command}"]
    if cfg is not None:
        parts.extend([
            f"preset={cfg.preset or 'none'}",
            f"runner={cfg.test_runner}",
            f"invoker={cfg.test_invoker}",
        ])
    print(_c(_DIM, " · ".join(parts)))


def section(name: str) -> None:
    """`── name ─────…` stage/sub-stage header, sized to the terminal."""
    if not is_verbose():
        return
    width = _term_width()
    prefix = f"── {name} "
    fill = max(3, width - len(prefix))
    print(f"{prefix}{'─' * fill}")


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
    Minimal-default mode suppresses ok/warn rows — only failures carry signal for agents.
    """
    if not is_verbose() and state != "fail":
        return
    width = _term_width()
    color = _STATE_COLORS[state]
    label_tag = f"[{label}]"
    status_txt = _c(color, status)
    detail_txt = _c(_DIM, detail) if detail else ""
    # Status pinned right; detail (if any) sits left of it with a one-space gap.
    suffix = f"{detail_txt} {status_txt}" if detail_txt else status_txt
    suffix_len = _plain_len(suffix)
    prefix = f"  {label_tag:<{LABEL_WIDTH}} "
    used = len(prefix) + len(command) + 1 + suffix_len
    if used <= width:
        padding = " " * (width - len(prefix) - len(command) - suffix_len)
        print(f"{prefix}{command}{padding}{suffix}")
        return
    # Truncate command to fit
    max_cmd = max(10, width - len(prefix) - suffix_len - 2)
    trimmed = command[: max_cmd - 1] + "…" if len(command) > max_cmd else command
    padding = " " * max(1, width - len(prefix) - len(trimmed) - suffix_len)
    print(f"{prefix}{trimmed}{padding}{suffix}")


def kv_block(pairs: list[tuple[str, str]], *, indent: str = "  ", gap: int = 1) -> None:
    """Aligned `key    value` block. Empty `pairs` is a no-op."""
    if not pairs:
        return
    key_width = max(len(k) for k, _ in pairs)
    for key, value in pairs:
        print(f"{indent}{key:<{key_width}}{' ' * gap}{value}")


def message_list(items: list[str], *, empty: str = "none", indent: str = "  ") -> None:
    """Print bullet messages with a consistent empty state."""
    if not items:
        print(f"{indent}{empty}")
        return
    for item in items:
        print(f"{indent}- {item}")


def stage_footer(elapsed_s: float) -> None:
    """`Completed in X.Ys` footer."""
    if not is_verbose():
        return
    print(f"\n{_c(_DIM, f'Completed in {elapsed_s:.1f}s')}")


def command_footer(start_time: float) -> None:
    """Print an elapsed footer for non-stage commands."""
    stage_footer(time.monotonic() - start_time)


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
