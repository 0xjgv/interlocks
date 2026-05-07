"""Global gate skip parsing and execution helpers."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Literal

from interlocks import ui
from interlocks.config import SKIP_LABELS, load_config

if TYPE_CHECKING:
    from collections.abc import Callable

    from interlocks.runner import Task


SkipSource = Literal["cli", "env", "project"]

_ENV_NAME = "INTERLOCKS_SKIP"


@dataclass(frozen=True)
class SkipPolicy:
    labels: frozenset[str]
    source: SkipSource

    def enabled(self, label: str) -> bool:
        return label in self.labels


@cache
def current_skip_policy() -> SkipPolicy:
    raw = _cli_raw()
    if raw is not None:
        return SkipPolicy(_parse_csv(raw, source="--skip"), "cli")
    raw = os.environ.get(_ENV_NAME)
    if raw is not None:
        return SkipPolicy(_parse_csv(raw, source=_ENV_NAME), "env")
    return SkipPolicy(load_config().skip, "project")


def maybe_print_skip_banner(policy: SkipPolicy) -> None:
    if not policy.labels or ui.is_quiet():
        return
    labels = ", ".join(sorted(policy.labels))
    print(f"  skips active ({policy.source}): {labels}")


def filter_tasks(tasks: list[Task], policy: SkipPolicy | None = None) -> list[Task]:
    from interlocks.runner import _default_label  # noqa: PLC0415  (breaks runner↔skip cycle)

    policy = policy or current_skip_policy()
    filtered: list[Task] = []
    for task in tasks:
        label = task.label or _default_label(task.description)
        if policy.enabled(label):
            warn_skipped(label)
        else:
            filtered.append(task)
    return filtered


def run_unless_skipped(
    label: str, run: Callable[[], None], policy: SkipPolicy | None = None
) -> None:
    policy = policy or current_skip_policy()
    if policy.enabled(label):
        warn_skipped(label)
        return
    run()


def warn_skipped(label: str, detail: str | None = None) -> None:
    from interlocks.runner import warn_skip  # noqa: PLC0415  (breaks runner↔skip cycle)

    message = f"{label}: skipped by global skip policy"
    if detail:
        message = f"{message} — {detail}"
    warn_skip(message)


def validate_cli_skip() -> None:
    raw = _cli_raw()
    if raw is not None:
        _parse_csv(raw, source="--skip")


def _cli_raw() -> str | None:
    for arg in sys.argv[1:]:
        if arg == "--skip":
            _fail_skip_usage("usage: --skip=<label>[,<label>...] (known: " + _known_labels() + ")")
        if arg.startswith("--skip="):
            return arg.split("=", 1)[1]
    return None


def _parse_csv(raw: str, *, source: str) -> frozenset[str]:
    labels = [cleaned for raw_label in raw.split(",") if (cleaned := raw_label.strip().lower())]
    unknown = sorted(set(labels) - SKIP_LABELS)
    if unknown:
        _fail_skip_usage(
            f"unknown skip label(s) for {source}: {', '.join(unknown)} (known: {_known_labels()})"
        )
    return frozenset(labels)


def _known_labels() -> str:
    return ",".join(sorted(SKIP_LABELS))


def _fail_skip_usage(message: str) -> None:
    print(f"interlocks: {message}", file=sys.stderr)
    raise SystemExit(2)
