"""Shared helpers for idempotent scaffold commands."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from pathlib import Path

ScaffoldAction: TypeAlias = str
ScaffoldFile: TypeAlias = dict[str, str]


def scaffold_file(path: str, action: ScaffoldAction) -> ScaffoldFile:
    return {"path": path, "action": action}


def scaffold_status(files: list[ScaffoldFile]) -> str:
    if files and all(file["action"] == "created" for file in files):
        return "created"
    return "scaffold-present"


def created_paths(files: list[ScaffoldFile]) -> list[str]:
    return [file["path"] for file in files if file["action"] == "created"]


def ensure_text_file(target: Path, content: str) -> ScaffoldAction:
    if target.exists():
        return "kept"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return "created"


def ensure_bytes_file(target: Path, content: bytes) -> ScaffoldAction:
    if target.exists():
        return "kept"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return "created"
