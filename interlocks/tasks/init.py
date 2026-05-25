"""Scaffold a greenfield Python project in the current working directory.

Writes ``pyproject.toml`` (from a bundled template), ``tests/__init__.py``, and
``tests/test_smoke.py``. Refuses to run when a ``pyproject.toml`` is already
present, and preserves existing test scaffold files. Stdlib-only.
"""

from __future__ import annotations

import sys
from pathlib import Path

from interlocks import ui
from interlocks.defaults_path import path as defaults_path
from interlocks.runner import Task, fail_skip, section
from interlocks.scaffold import (
    ScaffoldFile,
    created_paths,
    ensure_bytes_file,
    ensure_text_file,
    scaffold_file,
    scaffold_status,
)

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
    files: list[ScaffoldFile] = [
        scaffold_file(
            "pyproject.toml",
            ensure_text_file(
                pyproject,
                template.replace("{project_name}", cwd.name),
            ),
        )
    ]

    targets["tests"].mkdir(exist_ok=True)
    files.append(
        scaffold_file(
            "tests/__init__.py",
            ensure_text_file(targets["tests/__init__.py"], ""),
        )
    )
    files.append(
        scaffold_file(
            "tests/test_smoke.py",
            ensure_bytes_file(
                targets["tests/test_smoke.py"],
                defaults_path("scaffold_test_example.py").read_bytes(),
            ),
        )
    )
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


def _init_success_payload(project_name: str, files: list[ScaffoldFile]) -> dict[str, object]:
    return {
        "command": "init",
        "passed": True,
        "status": scaffold_status(files),
        "project_name": project_name,
        "created": created_paths(files),
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
