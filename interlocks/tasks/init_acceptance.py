"""Scaffold the pytest-bdd canonical layout under the project's test_dir.

Writes three files from bundled templates; refuses to overwrite anything that
already exists so re-running is safe. Stdlib-only.
"""

from __future__ import annotations

import sys

from interlocks import ui
from interlocks.config import load_config
from interlocks.defaults_path import path as defaults_path
from interlocks.runner import fail_skip, section

_INIT_ACCEPTANCE_OUTPUTS = (
    "tests/features/example.feature",
    "tests/step_defs/test_example.py",
    "tests/step_defs/conftest.py",
)
_INIT_ACCEPTANCE_NEXT_ACTIONS = (
    "Add `pytest-bdd>=8` to test/dev dependencies if it is missing.",
    "Create or sync the project environment if `interlocks doctor` reports one missing.",
    "Replace the example scenario with project behavior.",
    "Run `interlocks acceptance`.",
)
_INIT_ACCEPTANCE_TEMPLATES = (
    ("features/example.feature", "bdd_example.feature"),
    ("step_defs/test_example.py", "bdd_test_example.py"),
    ("step_defs/conftest.py", "bdd_conftest.py"),
)


def cmd_init_acceptance() -> None:
    section("Init acceptance (pytest-bdd)")
    cfg = load_config()
    test_dir = cfg.test_dir
    test_dir.mkdir(parents=True, exist_ok=True)

    targets = [(test_dir / relpath, template) for relpath, template in _INIT_ACCEPTANCE_TEMPLATES]

    existing = [t for t, _ in targets if t.exists()]
    if existing:
        rels = [cfg.relpath(p) for p in existing]
        if ui.is_json():
            ui.print_json(_init_acceptance_refusal_payload(rels))
            sys.exit(1)
        fail_skip(f"init-acceptance: refusing to overwrite existing files: {', '.join(rels)}")

    for target, template in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(defaults_path(template).read_bytes())
        if not ui.is_json():
            print(f"created {cfg.relpath(target)}")
    if ui.is_json():
        ui.print_json(_init_acceptance_success_payload())
        return
    _print_init_acceptance_next_steps()


def _print_init_acceptance_next_steps() -> None:
    for action in _INIT_ACCEPTANCE_NEXT_ACTIONS:
        print(f"next: {action[0].lower()}{action[1:]}")


def _init_acceptance_success_payload() -> dict[str, object]:
    return {
        "command": "init-acceptance",
        "passed": True,
        "status": "created",
        "created": list(_INIT_ACCEPTANCE_OUTPUTS),
        "next_actions": list(_INIT_ACCEPTANCE_NEXT_ACTIONS),
    }


def _init_acceptance_refusal_payload(existing_paths: list[str]) -> dict[str, object]:
    return {
        "command": "init-acceptance",
        "passed": False,
        "status": "refused",
        "error": f"refusing to overwrite existing files: {', '.join(existing_paths)}",
        "existing_paths": existing_paths,
        "created": [],
        "next_actions": [
            "Inspect existing acceptance files before scaffolding the example layout."
        ],
    }
