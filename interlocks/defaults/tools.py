"""Pinned versions of the CLI tools interlocks dispatches via uvx / uv run.

interlocks ships zero runtime deps: every gate is invoked through ``uvx`` (or
``uv run --with``) at the version named here. Resolution chain — strict equality
— mirrors the threshold resolver in :mod:`interlocks.config`:

1. CLI flag (no flag exists today; placeholder for a future ``--tool-pin=``).
2. ``[tool.interlocks.tools]`` in the project's ``pyproject.toml``.
3. ``DEFAULTS`` below.

The companion ``tools.txt`` (regenerated at release with
``uv pip compile --generate-hashes``) ships hash-pinned wheels alongside this
table so ``interlocks warm`` can pre-fetch them with ``--require-hashes``.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

DEFAULTS: Mapping[str, str] = MappingProxyType({
    "basedpyright": "1.39.3",
    "coverage": "7.13.5",
    "deptry": "0.25.1",
    "import-linter": "2.8",
    "interlocks-mutmut": "3.5.1",
    "lizard": "1.22.1",
    "pip-audit": "2.10.0",
    "ruff": "0.15.12",
})

# Console-script names that diverge from the package name. Consumed by the
# ``uvx``/``uv run --with`` argv builders so warmers and analyzers agree on the
# entrypoint without each call site re-encoding the divergence.
ENTRYPOINTS: Mapping[str, str] = MappingProxyType({
    "import-linter": "lint-imports",
})

# Defends against dependency-confusion in mirrored / private-index environments —
# the first matching index wins instead of resolving the highest version across
# every configured index. Shared by ``runner.uvx_tool`` / ``runner.uv_run_with``
# and ``config.coverage_invoker_prefix`` so the flag pair has one source of truth.
UV_INDEX_FLAG: tuple[str, str] = ("--index-strategy", "first-index")


def default_pin(name: str) -> str:
    """Return the bundled pin for ``name``; raise ``KeyError`` if unknown."""
    return DEFAULTS[name]


def entrypoint(name: str) -> str:
    """Return the console-script name for ``name``; defaults to the package name."""
    return ENTRYPOINTS.get(name, name)
