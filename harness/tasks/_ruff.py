"""Shared helpers for the four ruff-backed tasks (lint/fix/format/format-check)."""

from __future__ import annotations

from harness.config import load_config
from harness.defaults_path import config_flag_if_absent


def ruff_config_args() -> list[str]:
    """Return ``['--config', <bundled-ruff.toml>]`` iff the project has no ruff config.

    `ruff check` / `ruff format` each accept a single ``--config`` flag. Emitting
    this prefix lets every ruff task fall back to the bundled defaults without
    overriding anything the user has configured.
    """
    return config_flag_if_absent(
        load_config(),
        section="ruff",
        filename="ruff.toml",
        flag="--config",
        sidecars=("ruff.toml", ".ruff.toml"),
    )
