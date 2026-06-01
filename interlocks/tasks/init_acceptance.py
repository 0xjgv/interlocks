"""Scaffold the pytest-bdd canonical layout under the project's test_dir.

Writes missing bundled files and preserves existing files so re-running is safe.
Stdlib-only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from interlocks import ui
from interlocks.acceptance_status import feature_files
from interlocks.config import load_config
from interlocks.defaults_path import path as defaults_path
from interlocks.runner import section
from interlocks.scaffold import (
    ScaffoldFile,
    created_paths,
    ensure_bytes_file,
    next_actions_without_declared_dependency,
    scaffold_file,
    scaffold_status,
)

if TYPE_CHECKING:
    from pathlib import Path

    from interlocks.config import InterlockConfig

_INIT_ACCEPTANCE_OUTPUTS = (
    "tests/features/example.feature",
    "tests/step_defs/test_example.py",
    "tests/step_defs/conftest.py",
)
_INIT_ACCEPTANCE_DEP_ACTION = "Add `pytest-bdd>=8` to test/dev dependencies if it is missing."
_INIT_ACCEPTANCE_NEXT_ACTIONS = (
    _INIT_ACCEPTANCE_DEP_ACTION,
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

    files: list[ScaffoldFile] = []
    for target, template in _init_acceptance_targets(test_dir):
        files.append(
            scaffold_file(
                cfg.relpath(target),
                ensure_bytes_file(target, defaults_path(template).read_bytes()),
            )
        )

    if ui.is_json():
        ui.print_json(_init_acceptance_success_payload(cfg, files))
        return
    for file in files:
        print(f"{file['action']} {file['path']}")
    _print_init_acceptance_next_steps(cfg)


def _print_init_acceptance_next_steps(cfg: InterlockConfig) -> None:
    ui.print_next_actions(_init_acceptance_next_actions(cfg))


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


def _init_acceptance_success_payload(
    cfg: InterlockConfig, files: list[ScaffoldFile]
) -> dict[str, object]:
    return {
        "command": "init-acceptance",
        "passed": True,
        "status": scaffold_status(files),
        "created": created_paths(files),
        "files": files,
        "next_actions": list(_init_acceptance_next_actions(cfg)),
    }


def _init_acceptance_next_actions(cfg: InterlockConfig) -> tuple[str, ...]:
    return next_actions_without_declared_dependency(
        cfg.pyproject,
        dependency="pytest-bdd",
        dependency_action=_INIT_ACCEPTANCE_DEP_ACTION,
        actions=_INIT_ACCEPTANCE_NEXT_ACTIONS,
    )


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
