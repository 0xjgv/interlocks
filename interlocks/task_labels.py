"""Shared task label helpers."""

from __future__ import annotations


def default_label(description: str) -> str:
    return description.split(" ", 1)[0].lower().rstrip(":")
