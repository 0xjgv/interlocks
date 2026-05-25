"""Scaffold the pytest-bdd canonical layout under the project's test_dir.

Writes missing bundled files and preserves existing files so re-running is safe.
Stdlib-only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeAlias

from interlocks import ui
from interlocks.acceptance_status import feature_files
from interlocks.config import load_config
from interlocks.defaults_path import path as defaults_path
from interlocks.runner import section

if TYPE_CHECKING:
    from pathlib import Path

    from interlocks.config import InterlockConfig

_ScaffoldFile: TypeAlias = dict[str, str]

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
    domain_files = domain_acceptance_feature_files(cfg)
    if domain_files:
        if ui.is_json():
            ui.print_json(_init_acceptance_domain_payload(cfg, domain_files))
            return
        target = cfg.features_dir or (cfg.test_dir / "features")
        print(f"kept {cfg.relpath(target)}/")
        print("next: run `interlocks acceptance`")
        return

    files: list[_ScaffoldFile] = []
    for target, template in _init_acceptance_targets(test_dir):
        files.append({
            "path": cfg.relpath(target),
            "action": _ensure_scaffold_file(target, template),
        })

    if ui.is_json():
        ui.print_json(_init_acceptance_success_payload(files))
        return
    for file in files:
        print(f"{file['action']} {file['path']}")
    _print_init_acceptance_next_steps()


def _print_init_acceptance_next_steps() -> None:
    for action in _INIT_ACCEPTANCE_NEXT_ACTIONS:
        print(f"next: {action[0].lower()}{action[1:]}")


def domain_acceptance_feature_files(cfg: InterlockConfig) -> list[Path]:
    """Return feature files excluding the unchanged scaffold example."""
    return [path for path in feature_files(cfg.features_dir) if not _is_scaffold_feature(path)]


def _is_scaffold_feature(path: Path) -> bool:
    if path.name != "example.feature":
        return False
    try:
        return path.read_bytes() == defaults_path("bdd_example.feature").read_bytes()
    except OSError:
        return False


def _init_acceptance_targets(test_dir: Path) -> tuple[tuple[Path, str], ...]:
    return tuple(
        (test_dir / relpath, template) for relpath, template in _INIT_ACCEPTANCE_TEMPLATES
    )


def _ensure_scaffold_file(target: Path, template: str) -> str:
    if target.exists():
        return "kept"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(defaults_path(template).read_bytes())
    return "created"


def _init_acceptance_status(files: list[_ScaffoldFile]) -> str:
    if files and all(file["action"] == "created" for file in files):
        return "created"
    return "scaffold-present"


def _init_acceptance_success_payload(files: list[_ScaffoldFile]) -> dict[str, object]:
    return {
        "command": "init-acceptance",
        "passed": True,
        "status": _init_acceptance_status(files),
        "created": [file["path"] for file in files if file["action"] == "created"],
        "files": files,
        "next_actions": list(_INIT_ACCEPTANCE_NEXT_ACTIONS),
    }


def _init_acceptance_domain_payload(
    cfg: InterlockConfig, domain_files: list[Path]
) -> dict[str, object]:
    return {
        "command": "init-acceptance",
        "passed": True,
        "status": "domain-acceptance-present",
        "created": [],
        "files": [],
        "domain_acceptance_feature_count": len(domain_files),
        "domain_acceptance_features": [cfg.relpath(path) for path in domain_files],
        "next_actions": ["Run `interlocks acceptance`."],
    }
