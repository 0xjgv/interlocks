"""Scaffold a greenfield Python project in the current working directory.

Writes ``pyproject.toml`` (from a bundled template), ``tests/__init__.py``, and
``tests/test_smoke.py``. Refuses to run when a ``pyproject.toml`` is already
present, and preserves existing test scaffold files. Stdlib-only.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TypeAlias

from interlocks import ui
from interlocks.defaults_path import path as defaults_path
from interlocks.runner import Task, fail_skip, section

_ScaffoldFile: TypeAlias = dict[str, str]
_INIT_OUTPUTS = ("pyproject.toml", "tests/__init__.py", "tests/test_smoke.py")
_INIT_NEXT_ACTIONS = (
    "Run `interlocks presets set progressive` for ratcheting defaults.",
    "Run `interlocks init-properties` to scaffold property tests.",
)


def task_init() -> Task | None:
    """Not a gate — ``init`` is a one-shot scaffolding utility."""
    return None


def cmd_init() -> None:
    section("Init project")
    cwd = Path.cwd()
    targets = _init_targets(cwd)
    pyproject = targets["pyproject.toml"]
    if pyproject.exists():
        if ui.is_json():
            ui.print_json(_init_refusal_payload("pyproject.toml"))
            sys.exit(1)
        fail_skip("init: refusing to overwrite existing pyproject.toml")

    template = defaults_path("scaffold_pyproject.toml").read_text(encoding="utf-8")
    files: list[_ScaffoldFile] = [
        {
            "path": "pyproject.toml",
            "action": _ensure_text_file(
                pyproject,
                template.replace("{project_name}", cwd.name),
            ),
        }
    ]

    targets["tests"].mkdir(exist_ok=True)
    files.append({
        "path": "tests/__init__.py",
        "action": _ensure_text_file(targets["tests/__init__.py"], ""),
    })
    files.append({
        "path": "tests/test_smoke.py",
        "action": _ensure_bytes_file(
            targets["tests/test_smoke.py"],
            defaults_path("scaffold_test_example.py").read_bytes(),
        ),
    })
    if ui.is_json():
        ui.print_json(_init_success_payload(cwd.name, files))
        return
    for file in files:
        print(f"{file['action']} {file['path']}")
    _print_init_next_steps()


def _print_init_next_steps() -> None:
    for action in _INIT_NEXT_ACTIONS:
        print(f"next: {action[0].lower()}{action[1:]}")


def _init_targets(cwd: Path) -> dict[str, Path]:
    return {
        "pyproject.toml": cwd / "pyproject.toml",
        "tests": cwd / "tests",
        "tests/__init__.py": cwd / "tests" / "__init__.py",
        "tests/test_smoke.py": cwd / "tests" / "test_smoke.py",
    }


def _ensure_text_file(target: Path, content: str) -> str:
    if target.exists():
        return "kept"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return "created"


def _ensure_bytes_file(target: Path, content: bytes) -> str:
    if target.exists():
        return "kept"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return "created"


def _init_status(files: list[_ScaffoldFile]) -> str:
    if files and all(file["action"] == "created" for file in files):
        return "created"
    return "scaffold-present"


def _init_success_payload(project_name: str, files: list[_ScaffoldFile]) -> dict[str, object]:
    return {
        "command": "init",
        "passed": True,
        "status": _init_status(files),
        "project_name": project_name,
        "created": [file["path"] for file in files if file["action"] == "created"],
        "files": files,
        "next_actions": list(_INIT_NEXT_ACTIONS),
    }


def _init_refusal_payload(existing_path: str) -> dict[str, object]:
    return {
        "command": "init",
        "passed": False,
        "status": "refused",
        "error": f"refusing to overwrite existing {existing_path}",
        "existing_path": existing_path,
        "created": [],
        "next_actions": [
            "Run from an empty directory, or inspect existing project files before scaffolding."
        ],
    }
