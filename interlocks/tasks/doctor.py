"""Adoption diagnostic: report readiness, blockers, warnings, and next steps.

``doctor`` is intentionally lightweight and static. It reads local config, checks
filesystem paths and PATH resolution, and never runs tests, typechecking, coverage,
mutation, dependency audit, or network-dependent checks.
"""

from __future__ import annotations

import shutil
import sys
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from interlocks import ui
from interlocks.agent_contract import SCHEMA_VERSION, doctor_agent_contract
from interlocks.config import (
    CREATE_PROJECT_ENV_HINT,
    InterlockConfigError,
    find_project_root,
    kv_with_source,
    load_config,
    project_env_ready,
)
from interlocks.crash.storage import cache_dir as _crash_cache_dir
from interlocks.detect import expected_target_interpreter
from interlocks.setup_state import (
    acceptance_scaffold_present,
    ci_workflow_present,
    interlock_config_block_present,
    is_git_repo,
    setup_artifact_statuses,
)
from interlocks.tasks.properties import domain_property_test_files, property_test_files

if TYPE_CHECKING:
    from pathlib import Path

    from interlocks.config import InterlockConfig
    from interlocks.runner import Task
    from interlocks.ui import State

_INERT_DETAIL = "not applicable"


@dataclass(frozen=True)
class CheckRow:
    """One row in the Setup Checklist — mirrors ``ui.row`` args."""

    label: str
    target: str
    detail: str
    state: State


@dataclass(frozen=True)
class _DoctorReport:
    """Computed doctor state, shared by every render path."""

    project_root: Path
    cfg: InterlockConfig | None
    pyproject_path: Path
    rows: list[CheckRow]
    failures: list[str]
    blockers: list[str]
    warnings: list[str]
    is_blocked: bool
    gap_count: int


def task_doctor() -> Task | None:
    """Doctor is CLI-only — never runs as a composable ``Task``."""
    return None


def cmd_doctor() -> None:
    report = _build_doctor_report()

    if ui.is_json():
        _render_doctor_json(report)
    elif ui.is_verbose():
        _render_doctor_verbose(report)
    else:
        status, _summary = _readiness(report.is_blocked, report.gap_count)
        print(f"doctor: {status}")
        for line in (*report.failures, *report.blockers):
            print(f"  - {line}")
        if not report.is_blocked:
            _print_capped(_gap_lines(report.rows), limit=3)

    if report.failures:
        sys.exit(1)
    if report.is_blocked and "--strict" in sys.argv:
        sys.exit(2)


def _build_doctor_report() -> _DoctorReport:
    """Collect blockers, warnings, and setup rows into a single report value."""
    project_root = find_project_root()
    pyproject_path = project_root / "pyproject.toml"

    warnings: list[str] = []
    blockers: list[str] = []
    failures: list[str] = []

    cfg = _safe_load_config(pyproject_path, failures) if pyproject_path.is_file() else None
    _collect_blockers(cfg, pyproject_path, blockers)
    _collect_tool_blockers(cfg, blockers)

    rows = _collect_setup_rows(project_root, cfg, pyproject_path)
    is_blocked = bool(blockers or failures or any(r.state == "fail" for r in rows))
    gap_count = len(_actionable_gap_rows(rows))
    return _DoctorReport(
        project_root=project_root,
        cfg=cfg,
        pyproject_path=pyproject_path,
        rows=rows,
        failures=failures,
        blockers=blockers,
        warnings=warnings,
        is_blocked=is_blocked,
        gap_count=gap_count,
    )


def _render_doctor_json(report: _DoctorReport) -> None:
    """Emit the doctor report as a single machine-readable JSON object."""
    status, _summary = _readiness(report.is_blocked, report.gap_count)
    next_steps = _next_steps(
        report.rows,
        report.is_blocked,
        blockers=(*report.failures, *report.blockers),
    )
    ui.print_json({
        "command": "doctor",
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "blockers": [{"message": m} for m in (*report.failures, *report.blockers)],
        "warnings": [{"message": m} for m in _warning_lines(report)],
        "detected": _detected_json(report.project_root, report.cfg, report.pyproject_path),
        "setup_checklist": [
            {"name": r.label, "target": r.target, "detail": r.detail, "state": r.state}
            for r in report.rows
        ],
        "next_steps": [{"message": step} for step in next_steps],
        "agent": doctor_agent_contract(
            status=status,
            is_blocked=report.is_blocked,
            next_steps=next_steps,
        ),
    })


def _render_doctor_verbose(report: _DoctorReport) -> None:
    """Render the full sectioned doctor report (verbose mode)."""
    ui.section("Readiness")
    _print_readiness(report.is_blocked, report.gap_count)
    ui.section("Detected Configuration")
    _print_configuration(report.project_root, report.cfg, report.pyproject_path)
    ui.section("Setup Checklist")
    _render_setup_checklist(report.rows)
    ui.section("Blockers")
    ui.message_list([*report.failures, *report.blockers], empty="none")
    ui.section("Warnings")
    ui.message_list(_warning_lines(report), empty="none")
    ui.section("Next Steps")
    ui.message_list(
        _next_steps(report.rows, report.is_blocked, blockers=(*report.failures, *report.blockers)),
        empty="Run `interlocks check` locally.",
    )


def _print_readiness(is_blocked: bool, gap_count: int) -> None:
    status, summary = _readiness(is_blocked, gap_count)
    print(f"  status                 {status}")
    print(f"  summary                {summary}")


def _readiness(is_blocked: bool, gap_count: int) -> tuple[str, str]:
    if is_blocked:
        return "blocked", "fix blockers before running `interlocks check`"
    if gap_count:
        suffix = "s" if gap_count != 1 else ""
        return f"ready ({gap_count} gap{suffix})", "see Setup Checklist for optional wiring"
    return "ready", "ready to try `interlocks check`"


def _print_capped(items: list[str], limit: int = 3) -> None:
    """Print up to ``limit`` bullets, then a single overflow bullet if truncated.

    Mirrors ``ui.message_list``'s two-space indent and ``- `` bullet so default-mode
    output aligns visually with the verbose Blockers/Warnings sections. The overflow
    line is itself a bullet.
    """
    for line in items[:limit]:
        print(f"  - {line}")
    if len(items) > limit:
        print(f"  - …{len(items) - limit} more, run --verbose for the full list")


def _gap_lines(rows: list[CheckRow]) -> list[str]:
    """One formatted line per ``warn``-state ``CheckRow``, in row order.

    These are the advisory gaps the ``ready (N gap[s])`` count is built from
    (``gap_count = len(_actionable_gap_rows(rows))``), so the printed detail
    and the verdict count always agree.
    """
    return [f"{row.label}: {row.detail}" for row in _actionable_gap_rows(rows)]


def _actionable_gap_rows(rows: list[CheckRow]) -> list[CheckRow]:
    """Warn rows that need user action; inert placeholders are not gaps."""
    return [row for row in rows if row.state == "warn" and row.detail != _INERT_DETAIL]


def _warning_lines(report: _DoctorReport) -> list[str]:
    return [*report.warnings, *_gap_lines(report.rows)]


def _safe_load_config(pyproject_path: Path, failures: list[str]) -> InterlockConfig | None:
    """Load config, recording a failure when ``pyproject.toml`` is unreadable."""
    try:
        return load_config()
    except (OSError, tomllib.TOMLDecodeError, InterlockConfigError) as exc:
        failures.append(f"cannot read {pyproject_path}: {exc}")
        return None


def _collect_blockers(
    cfg: InterlockConfig | None, pyproject_path: Path, blockers: list[str]
) -> None:
    if not pyproject_path.is_file():
        blockers.append("missing pyproject.toml; run `interlocks init` to scaffold")
        return
    if cfg is None:
        return
    if not cfg.src_dir.exists():
        blockers.append(f"missing source path: {cfg.src_dir_arg}")
    if not cfg.test_dir.exists():
        blockers.append(f"missing test path: {cfg.test_dir_arg}")
    if not project_env_ready(cfg):
        blockers.append(
            "no project environment — typecheck/test produce false negatives; "
            f"create one {CREATE_PROJECT_ENV_HINT}"
        )
    for unsupported in cfg.unsupported_presets:
        blockers.append(f"unsupported preset: {unsupported}")


def _collect_tool_blockers(cfg: InterlockConfig | None, blockers: list[str]) -> None:
    """Record blockers from the resolved tool config.

    The budgeted-mutation behavior is documented by `explain check` and
    `check --help`, so it is not surfaced here — it is not a warning.
    """
    if cfg is not None and cfg.test_invoker == "uv" and shutil.which("uv") is None:
        blockers.append("test_invoker is `uv`, but `uv` was not found on PATH")


def _collect_setup_rows(
    project_root: Path, cfg: InterlockConfig | None, pyproject_path: Path
) -> list[CheckRow]:
    rows: list[CheckRow] = [_pyproject_row(pyproject_path)]
    if cfg is None or not pyproject_path.is_file():
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
        _properties_row(cfg),
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
    return CheckRow("preset", "(none)", "run `interlocks presets set progressive`", "warn")


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
    if project_env_ready(cfg):
        return CheckRow("venv", target, "missing", "warn")
    return CheckRow("venv", target, "missing — typecheck/test blocked", "fail")


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
        return not is_git_repo(project_root)
    if label == "claude hook":
        claude_dir = project_root / ".claude"
        return not claude_dir.is_dir() and not (claude_dir / "settings.json").is_file()
    return False


def _ci_workflow_row(project_root: Path) -> CheckRow:
    target = ".github/workflows/*.yml"
    if ci_workflow_present(project_root):
        return CheckRow("ci workflow", target, "present", "ok")
    return CheckRow("ci workflow", target, "run `interlocks setup --ci=github`", "warn")


def _acceptance_row(cfg: InterlockConfig) -> CheckRow:
    features_target = cfg.features_dir_arg or "tests/features/"
    if cfg.acceptance_runner == "off":
        return CheckRow("acceptance", "(disabled)", _INERT_DETAIL, "warn")
    if acceptance_scaffold_present(cfg):
        return CheckRow("acceptance", features_target, "scaffolded", "ok")
    if cfg.acceptance_runner is not None:
        return CheckRow(
            "acceptance", features_target, "run `interlocks init --acceptance`", "warn"
        )
    return CheckRow("acceptance", features_target, "not wired", "warn")


def _properties_row(cfg: InterlockConfig) -> CheckRow:
    target = cfg.properties_dir_arg or "properties"
    files = property_test_files(cfg)
    if domain_property_test_files(cfg):
        return CheckRow("properties", target, "detected", "ok")
    if files:
        return CheckRow("properties", target, "replace scaffold example", "warn")
    return CheckRow("properties", target, "run `interlocks init --properties`", "warn")


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


# Each rule maps a set of `CheckRow.label`s to the next-step bullet shown when
# any of those rows is in a `warn` (gap) state.
_NEXT_STEP_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("git hook", "claude hook", "agent docs", "claude skill"),
        "Run `interlocks setup` to install hooks, agent docs, and the Claude skill.",
    ),
    (
        ("interlocks cfg", "preset"),
        "Run `interlocks presets set progressive` to enable ratcheting defaults.",
    ),
    (("acceptance",), "Run `interlocks init --acceptance` to scaffold Gherkin tests."),
    (("properties",), "Run `interlocks init --properties` to scaffold property tests."),
    (
        ("ci workflow",),
        "Run `interlocks setup --ci=github` to install a GitHub Actions workflow, "
        "or wire `interlocks ci` manually.",
    ),
    (("venv",), "Create a venv (`uv sync` or `python -m venv .venv`)."),
)


def _next_steps(
    rows: list[CheckRow],
    is_blocked: bool,
    *,
    blockers: tuple[str, ...] = (),
) -> list[str]:
    if is_blocked:
        return _blocked_next_steps(rows, blockers)
    by_label = {r.label: r for r in rows}
    steps: list[str] = []
    for labels, step in _NEXT_STEP_RULES:
        for label in labels:
            row = by_label.get(label)
            if row is None or not _is_warn(by_label, label):
                continue
            steps.append(_properties_next_step(row) if label == "properties" else step)
            break
    return steps or ["Run `interlocks check` locally."]


def _blocked_next_steps(rows: list[CheckRow], blockers: tuple[str, ...]) -> list[str]:
    by_label = {row.label: row for row in rows}
    steps: list[str] = []
    for labels, message in _BLOCKED_ROW_STEPS:
        if any(_is_fail(by_label, label) for label in labels):
            steps.append(message)
    for needle, message in _BLOCKED_BLOCKER_STEPS:
        if any(needle in blocker for blocker in blockers):
            steps.append(message)
    return steps or ["Fix blockers in Setup Checklist above, then rerun `interlocks doctor`."]


_BLOCKED_ROW_STEPS = (
    (
        ("pyproject",),
        "Run `interlocks init` to scaffold a project, then rerun `interlocks doctor`.",
    ),
    (
        ("src dir", "test dir"),
        "Create the missing source/test paths or update `[tool.interlocks]`, "
        "then rerun `interlocks doctor`.",
    ),
    (
        ("venv",),
        "Create a project environment (`uv sync`, or "
        "`python -m venv .venv && pip install -e .`), then rerun `interlocks doctor`.",
    ),
)
_BLOCKED_BLOCKER_STEPS = (
    ("unsupported preset", "Choose a supported preset, then rerun `interlocks doctor`."),
    ("cannot read", "Fix `pyproject.toml`, then rerun `interlocks doctor`."),
)


def _is_warn(by_label: dict[str, CheckRow], label: str) -> bool:
    """True when ``label`` row is an actionable gap (warn, excluding inert placeholders)."""
    row = by_label.get(label)
    return row is not None and row.state == "warn" and row.detail != _INERT_DETAIL


def _is_fail(by_label: dict[str, CheckRow], label: str) -> bool:
    row = by_label.get(label)
    return row is not None and row.state == "fail"


def _properties_next_step(row: CheckRow) -> str:
    if row.detail == "replace scaffold example":
        return (
            f"Replace {row.target}/test_example_properties.py with domain invariants, "
            "then run `interlocks gate properties --profile=check`."
        )
    return "Run `interlocks init --properties` to scaffold property tests."


def _detected_json(
    project_root: Path, cfg: InterlockConfig | None, pyproject_path: Path
) -> dict[str, object]:
    """Detected-configuration values for the `doctor --json` `detected` object."""
    detected: dict[str, object] = {
        "project_root": str(project_root),
        "pyproject_path": str(pyproject_path) if pyproject_path.is_file() else None,
    }
    if cfg is None:
        detected.update({"preset": None, "src_dir": None, "test_dir": None})
    else:
        detected.update({
            "preset": cfg.preset,
            "src_dir": cfg.src_dir_arg,
            "test_dir": cfg.test_dir_arg,
        })
    return detected


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


_DERIVED_CFG_KEYS: tuple[str, ...] = (
    "coverage_min",
    "crap_max",
    "enforce_crap",
    "run_mutation_in_ci",
    "enforce_mutation",
    "mutation_ci_mode",
    "run_acceptance_in_check",
    "run_properties_in_check",
)


def _cfg_rows(cfg: InterlockConfig) -> list[tuple[str, object]]:
    rows: list[tuple[str, object]] = [
        ("preset", cfg.preset or "(none)"),
        ("src_dir", cfg.src_dir_arg),
        ("test_dir", cfg.test_dir_arg),
        ("test_runner", cfg.test_runner),
        ("test_invoker", cfg.test_invoker),
        ("features_dir", cfg.features_dir_arg if cfg.features_dir_arg is not None else "(none)"),
        (
            "properties_dir",
            cfg.properties_dir_arg if cfg.properties_dir_arg is not None else "(none)",
        ),
        (
            "acceptance_runner",
            cfg.acceptance_runner if cfg.acceptance_runner is not None else "(auto)",
        ),
    ]
    rows.extend((key, getattr(cfg, key)) for key in _DERIVED_CFG_KEYS)
    return rows
