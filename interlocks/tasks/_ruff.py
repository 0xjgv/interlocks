"""Shared core for the four ruff-backed tasks (lint/fix/format/format-check).

Per-task differences (subcommand args + labels) live in ``_RUFF_SPECS``; wrapper
modules call ``make_ruff_task`` to build the ``Task`` with bundled ``--config``
injected when the project owns no ruff config.
"""

from __future__ import annotations

from typing import NamedTuple

from interlocks.config import load_config
from interlocks.defaults_path import config_flag_if_absent
from interlocks.runner import Task, uvx_tool


def ruff_config_args() -> list[str]:
    """``['--config', <bundled-ruff.toml>]`` iff the project has no ruff config."""
    return config_flag_if_absent(
        load_config(),
        section="ruff",
        filename="ruff.toml",
        flag="--config",
        sidecars=("ruff.toml", ".ruff.toml"),
    )


class _RuffSpec(NamedTuple):
    args: tuple[str, ...]
    title: str
    label: str
    display: str


_RUFF_SPECS: dict[str, _RuffSpec] = {
    "lint": _RuffSpec(("check",), "Lint check", "lint", "ruff check"),
    "fix": _RuffSpec(("check", "--fix"), "Fix lint errors", "fix", "ruff check --fix"),
    "format": _RuffSpec(("format",), "Format code", "format", "ruff format"),
    "format-check": _RuffSpec(
        ("format", "--check"), "Format check", "format", "ruff format --check"
    ),
}


def make_ruff_task(name: str, files: list[str] | None = None) -> Task:
    """Build the ``Task`` for a registered ruff wrapper. ``files`` defaults to ``['.']``."""
    spec = _RUFF_SPECS[name]
    cfg = load_config()
    return Task(
        spec.title,
        uvx_tool(
            "ruff",
            *spec.args,
            *ruff_config_args(),
            *(files or ["."]),
            version=cfg.tool_version("ruff"),
        ),
        label=spec.label,
        display=spec.display,
    )
