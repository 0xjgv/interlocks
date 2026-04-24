"""Adoption diagnostic: report readiness, blockers, warnings, and next steps.

``doctor`` is intentionally lightweight and static. It reads local config, checks
filesystem paths and PATH resolution, and never runs tests, typechecking, coverage,
mutation, dependency audit, or network-dependent checks.
"""

from __future__ import annotations

import shutil
import sys
import time
import tomllib
from typing import TYPE_CHECKING

from harness import ui
from harness.config import find_project_root, kv_with_source, load_config
from harness.detect import expected_target_interpreter

if TYPE_CHECKING:
    from pathlib import Path

    from harness.config import HarnessConfig
    from harness.runner import Task

_BUNDLED_TOOLS = (
    "ruff",
    "basedpyright",
    "coverage",
    "mutmut",
    "pytest",
    "pip-audit",
    "deptry",
    "import-linter",
    "lizard",
)


def task_doctor() -> Task | None:
    """Doctor is CLI-only — never runs as a composable ``Task``."""
    return None


def cmd_doctor() -> None:
    start = time.monotonic()
    project_root = find_project_root()
    pyproject_path = project_root / "pyproject.toml"

    warnings: list[str] = []
    blockers: list[str] = []
    failures: list[str] = []

    cfg = _safe_load_config(pyproject_path, failures)
    _collect_blockers(cfg, pyproject_path, blockers)
    _collect_tool_warnings(project_root, cfg, warnings, blockers)
    is_blocked = bool(blockers or failures)

    ui.command_banner("doctor", cfg)
    ui.section("Readiness")
    if is_blocked:
        print("  status                 blocked")
        print("  summary                fix blockers before running `harness check`")
    else:
        print("  status                 ready")
        print("  summary                ready to try `harness check`")

    ui.section("Detected Configuration")
    _print_configuration(project_root, cfg, pyproject_path)

    ui.section("Blockers")
    _print_messages([*failures, *blockers], empty="none")

    ui.section("Warnings")
    _print_messages(warnings, empty="none")

    ui.section("Next Steps")
    _print_next_steps(is_blocked)
    ui.command_footer(start)

    if failures:
        sys.exit(1)


def _safe_load_config(pyproject_path: Path, failures: list[str]) -> HarnessConfig | None:
    """Load config, recording a failure when ``pyproject.toml`` is unreadable."""
    try:
        return load_config()
    except (OSError, tomllib.TOMLDecodeError) as exc:
        failures.append(f"cannot read {pyproject_path}: {exc}")
        return None


def _collect_blockers(
    cfg: HarnessConfig | None, pyproject_path: Path, blockers: list[str]
) -> None:
    if not pyproject_path.is_file():
        blockers.append("missing pyproject.toml; run `harness init` to scaffold")
    if cfg is None:
        return
    if not cfg.src_dir.exists():
        blockers.append(f"missing source path: {cfg.src_dir_arg}")
    if not cfg.test_dir.exists():
        blockers.append(f"missing test path: {cfg.test_dir_arg}")
    for unsupported in cfg.unsupported_presets:
        blockers.append(f"unsupported preset: {unsupported}")


def _collect_tool_warnings(
    project_root: Path,
    cfg: HarnessConfig | None,
    warnings: list[str],
    blockers: list[str],
) -> None:
    if cfg is not None and cfg.test_invoker == "uv" and shutil.which("uv") is None:
        blockers.append("test_invoker is `uv`, but `uv` was not found on PATH")

    for name in _BUNDLED_TOOLS:
        if shutil.which(name) is None:
            warnings.append(f"tool not found on PATH: {name}")

    venv_python = expected_target_interpreter(project_root)
    if not venv_python.is_file():
        warnings.append(f"no .venv found under project root ({venv_python})")


def _print_configuration(
    project_root: Path, cfg: HarnessConfig | None, pyproject_path: Path
) -> None:
    pairs: list[tuple[str, str]] = [("project_root", f"{project_root} (auto-detected)")]
    if pyproject_path.is_file():
        pairs.append(("pyproject.toml", f"{pyproject_path} (auto-detected)"))
    else:
        pairs.append(("pyproject.toml", "(missing)"))
    if cfg is None:
        ui.kv_block(pairs)
        return
    pairs.extend(kv_with_source(cfg, key, value) for key, value in _cfg_rows(cfg))
    ui.kv_block(pairs)


def _cfg_rows(cfg: HarnessConfig) -> list[tuple[str, object]]:
    features = cfg.features_dir_arg if cfg.features_dir_arg is not None else "(none)"
    acceptance = cfg.acceptance_runner if cfg.acceptance_runner is not None else "(auto)"
    rows: list[tuple[str, object]] = [
        ("preset", cfg.preset or "(none)"),
        ("src_dir", cfg.src_dir_arg),
        ("test_dir", cfg.test_dir_arg),
        ("test_runner", cfg.test_runner),
        ("test_invoker", cfg.test_invoker),
        ("features_dir", features),
        ("acceptance_runner", acceptance),
    ]
    for key in (
        "coverage_min",
        "crap_max",
        "enforce_crap",
        "run_mutation_in_ci",
        "enforce_mutation",
        "mutation_ci_mode",
        "run_acceptance_in_check",
    ):
        rows.append((key, getattr(cfg, key)))
    return rows


def _print_messages(messages: list[str], *, empty: str) -> None:
    ui.message_list(messages, empty=empty)


def _print_next_steps(blocked: bool) -> None:
    if blocked:
        print("  1. Fix the blockers listed above.")
        print("  2. Run `harness doctor` again.")
        print("  3. Run `harness check` once readiness is clear.")
        return
    print("  1. Run `harness check` locally.")
    print("  2. Wire CI with `harness ci` or the reusable pyharness GitHub Action.")
    print("  3. Optional: run `harness setup-hooks` to install local feedback hooks.")
