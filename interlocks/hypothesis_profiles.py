"""Shared Hypothesis profile definitions."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_REGISTERED_PROFILE_EXAMPLES = (
    ("check", 15),
    ("ci", 100),
    ("nightly", 500),
)
PROPERTY_PROFILES = ("check", "ci", "nightly", "default")


def register_hypothesis_profiles() -> None:
    """Register Interlocks' named Hypothesis profiles in the current process."""
    settings: Any = import_module("hypothesis").settings

    for name, max_examples in _REGISTERED_PROFILE_EXAMPLES:
        try:
            existing = settings.get_profile(name)
        except Exception as exc:
            if exc.__class__.__name__ != "InvalidArgument":
                raise
            existing = None
        if (
            existing is not None
            and existing.max_examples == max_examples
            and existing.deadline is None
        ):
            continue
        settings.register_profile(name, max_examples=max_examples, deadline=None)


def hypothesis_profile_setup_source() -> str:
    """Return self-contained Python source that registers the named profiles."""
    lines = ["from hypothesis import settings"]
    lines.extend(
        (f"settings.register_profile({name!r}, max_examples={max_examples}, deadline=None)")
        for name, max_examples in _REGISTERED_PROFILE_EXAMPLES
    )
    return "\n".join(lines)
