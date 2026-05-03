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
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from interlocks import ui
from interlocks.config import find_project_root, kv_with_source, load_config
from interlocks.crash.storage import cache_dir as _crash_cache_dir
from interlocks.detect import expected_target_interpreter
from interlocks.setup_state import (
    acceptance_scaffold_present,
    ci_workflow_present,
    interlock_config_block_present,
    setup_artifact_statuses,
)

if TYPE_CHECKING:
    from pathlib import Path

    from interlocks.config import InterlockConfig
    from interlocks.runner import Task
    from interlocks.ui import State

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
_INERT_DETAIL = "not applicable"


@dataclass(frozen=True)
class CheckRow:
    """One row in the Setup Checklist — mirrors ``ui.row`` args."""

    label: str
    target: str
    detail: str
    state: State


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

    rows = _collect_setup_rows(project_root, cfg, pyproject_path)
    is_blocked = bool(blockers or failures or any(r.state == "fail" for r in rows))
    gap_count = sum(1 for r in rows if r.state == "warn")

    ui.command_banner("doctor", cfg)
    ui.section("Readiness")
    _print_readiness(is_blocked, gap_count)

    ui.section("Detected Configuration")
    _print_configuration(project_root, cfg, pyproject_path)

    ui.section("Setup Checklist")
    _render_setup_checklist(rows)

    ui.section("Blockers")
    _print_messages([*failures, *blockers], empty="none")

    ui.section("Warnings")
    _print_messages(warnings, empty="none")

    ui.section("Next Steps")
    ui.message_list(
        _next_steps(rows, is_blocked),
        empty="Run `interlocks check` locally.",
    )
    ui.command_footer(start)

    if failures:
        sys.exit(1)


def _print_readiness(is_blocked: bool, gap_count: int) -> None:
    if is_blocked:
        print("  status                 blocked")
        print("  summary                fix blockers before running `interlocks check`")
        return
    if gap_count:
        suffix = "s" if gap_count != 1 else ""
        print(f"  status                 ready ({gap_count} gap{suffix})")
        print("  summary                see Setup Checklist for optional wiring")
        return
    print("  status                 ready")
    print("  summary                ready to try `interlocks check`")


def _safe_load_config(pyproject_path: Path, failures: list[str]) -> InterlockConfig | None:
    """Load config, recording a failure when ``pyproject.toml`` is unreadable."""
    try:
        return load_config()
    except (OSError, tomllib.TOMLDecodeError) as exc:
        failures.append(f"cannot read {pyproject_path}: {exc}")
        return None


def _collect_blockers(
    cfg: InterlockConfig | None, pyproject_path: Path, blockers: list[str]
) -> None:
    if not pyproject_path.is_file():
        blockers.append("missing pyproject.toml; run `interlocks init` to scaffold")
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
    cfg: InterlockConfig | None,
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


def _collect_setup_rows(
    project_root: Path, cfg: InterlockConfig | None, pyproject_path: Path
) -> list[CheckRow]:
    rows: list[CheckRow] = [_pyproject_row(pyproject_path)]
    if cfg is None:
        return rows
    rows.extend([
        _preset_row(cfg),
        _interlock_cfg_row(cfg),
        _src_dir_row(cfg),
        _test_dir_row(cfg),
        _venv_row(cfg),
        *_local_integration_rows(project_root),
        _ci_workflow_row(project_root),
        _acceptance_row(cfg),
        _crash_report_cache_row(),
    ])
    return rows


def _pyproject_row(pyproject_path: Path) -> CheckRow:
    if pyproject_path.is_file():
        return CheckRow("pyproject", "pyproject.toml", "present", "ok")
    return CheckRow("pyproject", "pyproject.toml", "missing", "fail")


def _preset_row(cfg: InterlockConfig) -> CheckRow:
    if cfg.preset:
        return CheckRow("preset", cfg.preset, "configured", "ok")
    return CheckRow("preset", "(none)", "using dataclass defaults", "warn")


def _interlock_cfg_row(cfg: InterlockConfig) -> CheckRow:
    if interlock_config_block_present(cfg):
        return CheckRow("interlocks cfg", "[tool.interlocks] block", "present", "ok")
    return CheckRow("interlocks cfg", "[tool.interlocks] block", "defaults apply", "warn")


def _src_dir_row(cfg: InterlockConfig) -> CheckRow:
    target = f"{cfg.src_dir_arg}/"
    if cfg.src_dir.exists():
        return CheckRow("src dir", target, "present", "ok")
    return CheckRow("src dir", target, "missing", "fail")


def _test_dir_row(cfg: InterlockConfig) -> CheckRow:
    target = f"{cfg.test_dir_arg}/"
    if cfg.test_dir.exists():
        return CheckRow("test dir", target, "present", "ok")
    return CheckRow("test dir", target, "missing", "fail")


def _venv_row(cfg: InterlockConfig) -> CheckRow:
    venv_python = expected_target_interpreter(cfg.project_root)
    target = cfg.relpath(venv_python)
    if venv_python.is_file():
        return CheckRow("venv", target, "present", "ok")
    return CheckRow("venv", target, "missing", "warn")


def _local_integration_rows(project_root: Path) -> list[CheckRow]:
    rows: list[CheckRow] = []
    for status in setup_artifact_statuses(project_root):
        if _is_inert_setup_artifact(project_root, status.label):
            rows.append(CheckRow(status.label, status.target, _INERT_DETAIL, "warn"))
            continue
        if status.installed:
            rows.append(
                CheckRow(status.label, status.target, status.artifact.installed_detail, "ok")
            )
            continue
        rows.append(CheckRow(status.label, status.target, "run `interlocks setup`", "warn"))
    return rows


def _is_inert_setup_artifact(project_root: Path, label: str) -> bool:
    if label == "git hook":
        return not (project_root / ".git").exists()
    if label == "claude hook":
        claude_dir = project_root / ".claude"
        return not claude_dir.is_dir() and not (claude_dir / "settings.json").is_file()
    return False


def _ci_workflow_row(project_root: Path) -> CheckRow:
    target = ".github/workflows/*.yml"
    if ci_workflow_present(project_root):
        return CheckRow("ci workflow", target, "present", "ok")
    return CheckRow("ci workflow", target, "not detected", "warn")


def _acceptance_row(cfg: InterlockConfig) -> CheckRow:
    features_target = cfg.features_dir_arg or "tests/features/"
    if cfg.acceptance_runner == "off":
        return CheckRow("acceptance", "(disabled)", _INERT_DETAIL, "warn")
    if acceptance_scaffold_present(cfg):
        return CheckRow("acceptance", features_target, "scaffolded", "ok")
    if cfg.acceptance_runner is not None:
        return CheckRow("acceptance", features_target, "run `interlocks init-acceptance`", "warn")
    return CheckRow("acceptance", features_target, "not wired", "warn")


def _crash_report_cache_row() -> CheckRow:
    """Surface the crash-reports cache: count and last-seen.

    Reads ``~/.cache/interlocks/crashes/`` (XDG_CACHE_HOME-aware) without
    importing transport — we don't want doctor to lazily pull in the browser
    machinery just to count files.
    """
    target = "~/.cache/interlocks/crashes/"
    try:
        directory = _crash_cache_dir()
    except OSError:
        return CheckRow("crash reports", target, "cache unreadable", "warn")

    files = sorted(directory.glob("*.json"))
    count = len(files)
    if count == 0:
        return CheckRow("crash reports", target, "0 cached", "ok")

    last_mtime = max(f.stat().st_mtime for f in files)
    last_seen = datetime.fromtimestamp(last_mtime, tz=UTC).strftime("%Y-%m-%d")
    return CheckRow(
        "crash reports",
        target,
        f"{count} cached (last seen: {last_seen})",
        "ok",
    )


def _render_setup_checklist(rows: list[CheckRow]) -> None:
    for row in rows:
        ui.row(row.label, row.target, row.state, detail=row.detail, state=row.state)


def _next_steps(rows: list[CheckRow], is_blocked: bool) -> list[str]:
    if is_blocked:
        return ["Fix blockers in Setup Checklist above, then rerun `interlocks doctor`."]
    by_label = {r.label: r for r in rows}
    steps = [
        step
        for labels, step in (
            (
                ("git hook", "claude hook", "agent docs", "claude skill"),
                "Run `interlocks setup` to install hooks, agent docs, and the Claude skill.",
            ),
            (
                ("interlocks cfg", "preset"),
                "Run `interlocks presets` to pick a preset (baseline, strict, legacy).",
            ),
            (("acceptance",), "Run `interlocks init-acceptance` to scaffold Gherkin tests."),
            (
                ("ci workflow",),
                "Wire CI via `interlocks ci` or the reusable interlocks GitHub Action.",
            ),
            (("venv",), "Create a venv (`uv sync` or `python -m venv .venv`)."),
        )
        if any(_is_warn(by_label, label) for label in labels)
    ]
    return steps or ["Run `interlocks check` locally."]


def _is_warn(by_label: dict[str, CheckRow], label: str) -> bool:
    """True when ``label`` row is an actionable gap (warn, excluding inert placeholders)."""
    row = by_label.get(label)
    return row is not None and row.state == "warn" and row.detail != _INERT_DETAIL


def _print_configuration(
    project_root: Path, cfg: InterlockConfig | None, pyproject_path: Path
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


def _cfg_rows(cfg: InterlockConfig) -> list[tuple[str, object]]:
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
