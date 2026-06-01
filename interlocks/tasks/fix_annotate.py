"""GitHub Actions PR annotations for the fix plan (Phase 5).

Reads ``.lintfix/plan.json`` (default) or ``.lintfix/optimize.json`` and prints
one workflow command per candidate so PR pages show inline advisory hints.

Intentionally non-failing: a missing plan file is treated as "nothing to
annotate" and exits 0, so CI workflows can wire this step unconditionally
(``if: always()``) without becoming a noise source.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from interlocks import ui
from interlocks.config import load_config, relpath
from interlocks.lintfix import escrow
from interlocks.runner import arg_value

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

Severity = Literal["notice", "warning"]
Source = Literal["plan", "optimize"]

_SEVERITY: dict[str, Severity] = {
    "auto": "notice",
    "escrow": "notice",
    "advisory": "warning",
}


@dataclass(frozen=True, slots=True)
class AnnotationResult:
    source: Source
    path: Path
    found: bool
    notice: int = 0
    warning: int = 0
    skip: int = 0

    @property
    def annotation_count(self) -> int:
        return self.notice + self.warning


def cmd_fix_annotate(*, source: Source | None = None, input_path: str | None = None) -> None:
    """Emit GitHub Actions annotations for the fix plan.

    ``source`` selects the JSON file under ``.lintfix/``; ``input_path`` overrides it.
    """
    src: Source = source or _arg_source()
    input_arg = input_path if input_path is not None else arg_value("--input=", "")
    project_root = load_config().project_root
    result = emit_annotations(
        project_root,
        source=src,
        input_path=input_arg,
        report_missing=True,
        emit_json=ui.is_json(),
    )
    if ui.is_json():
        ui.print_json(_fix_annotate_payload(project_root, result))


def emit_annotations(
    project_root: Path,
    *,
    source: Source,
    input_path: str = "",
    report_missing: bool = False,
    emit_json: bool = False,
) -> AnnotationResult:
    """Read the fix JSON for ``source`` and print one workflow command per candidate.

    The single implementation behind both ``fix-annotate`` and the inline
    ``fix-optimize --annotate`` path. Non-failing on a missing file (exits the
    caller's flow with no output); a malformed file is the one hard error.
    """
    path = _resolve_path(project_root, source, input_path)
    if not path.is_file():
        return _missing_annotation_result(
            project_root,
            source=source,
            path=path,
            report_missing=report_missing,
            emit_json=emit_json,
        )

    payload = _read_annotation_payload(project_root, source=source, path=path, emit_json=emit_json)
    counts = _collect_annotation_counts(payload, source=source, emit_json=emit_json)
    result = AnnotationResult(
        source=source,
        path=path,
        found=True,
        notice=counts["notice"],
        warning=counts["warning"],
        skip=counts["skip"],
    )
    _render_annotation_summary(project_root, result, emit_json=emit_json)
    return result


def _missing_annotation_result(
    project_root: Path,
    *,
    source: Source,
    path: Path,
    report_missing: bool,
    emit_json: bool,
) -> AnnotationResult:
    if report_missing and not emit_json:
        ui.gate_row(
            "fix-annotate",
            relpath(project_root, path),
            "ok",
            detail="no plan",
            state="ok",
        )
    return AnnotationResult(source=source, path=path, found=False)


def _read_annotation_payload(
    project_root: Path,
    *,
    source: Source,
    path: Path,
    emit_json: bool,
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        if emit_json:
            ui.print_json(_fix_annotate_error_payload(project_root, source, path, str(exc)))
            sys.exit(2)
        ui.row("fix-annotate", "parse", str(exc), state="fail")
        sys.exit(2)
    return payload if isinstance(payload, dict) else {}


def _collect_annotation_counts(
    payload: dict[str, Any],
    *,
    source: Source,
    emit_json: bool,
) -> dict[str, int]:
    counts = {"notice": 0, "warning": 0, "skip": 0}
    for c in _iter_candidates(payload, source):
        if c.get("classification") == "skip":
            counts["skip"] += 1
            continue
        for ann in _annotations_for(c):
            if not emit_json:
                print(ann.line)
            counts[ann.severity] += 1
    return counts


def _render_annotation_summary(
    project_root: Path,
    result: AnnotationResult,
    *,
    emit_json: bool,
) -> None:
    if emit_json:
        return
    if not emit_json:
        ui.section("fix-annotate")
        ui.kv_block([
            ("source", relpath(project_root, result.path)),
            ("notice", str(result.notice)),
            ("warning", str(result.warning)),
            ("skip", str(result.skip)),
        ])


def _arg_source() -> Source:
    value = arg_value("--source=", "plan")
    if value not in ("plan", "optimize"):
        if ui.is_json():
            ui.print_json({
                "command": "fix-annotate",
                "passed": False,
                "status": "invalid-source",
                "error": f"invalid source: {value!r}",
                "expected_sources": ["plan", "optimize"],
            })
            sys.exit(2)
        ui.row("fix-annotate", "source", f"invalid: {value!r}", state="fail")
        sys.exit(2)
    return value


def _resolve_path(project_root: Path, source: Source, override: str) -> Path:
    if override:
        return project_root / override
    filename = "optimize.json" if source == "optimize" else "plan.json"
    return escrow.lintfix_dir(project_root) / filename


def _iter_candidates(payload: dict[str, Any], source: Source) -> Iterable[dict[str, Any]]:
    if source == "optimize":
        for key in ("selected", "not_selected"):
            for c in _iter_candidate_dicts(payload.get(key)):
                flattened = _flatten_optimize(c)
                if flattened is not None:
                    yield flattened
        return
    yield from _iter_candidate_dicts(payload.get("candidates"))


def _iter_candidate_dicts(raw: object) -> Iterable[dict[str, Any]]:
    if not isinstance(raw, list):
        return
    yield from (item for item in raw if isinstance(item, dict))


def _flatten_optimize(c: dict[str, Any]) -> dict[str, Any] | None:
    """Map optimize-source fields onto the flat plan schema used by the formatter."""
    policy_mode = c.get("policy_mode")
    if not isinstance(policy_mode, str):
        return None
    cost = c.get("cost") or {}
    if not isinstance(cost, dict):
        cost = {}
    files = c.get("files") or []
    files_count = len(files) if isinstance(files, list | tuple) else 0
    return {
        **c,
        "classification": policy_mode,
        "files_touched": cost.get("files", files_count),
        "changed_lines_total": cost.get("changed_lines", 0),
        "changed_lines_outside_diff": cost.get("outside_diff", 0),
        "risk": cost.get("risk", 0),
    }


@dataclass(frozen=True, slots=True)
class _Annotation:
    line: str
    severity: Severity


def _annotations_for(c: dict[str, Any]) -> Iterable[_Annotation]:
    rule = c.get("rule")
    classification = c.get("classification")
    if not isinstance(rule, str) or not rule or not isinstance(classification, str):
        return
    severity = _SEVERITY.get(classification)
    if severity is None:
        return
    message = _escape_workflow_command_data(_format_message(c))
    raw_files = c.get("files") or []
    files = raw_files if isinstance(raw_files, list | tuple) else []
    if not files:
        yield _Annotation(f"::{severity}::{message}", severity)
        return
    for file_path in files:
        file_property = _escape_workflow_command_property(file_path)
        yield _Annotation(f"::{severity} file={file_property},line=1::{message}", severity)


def _format_message(c: dict[str, Any]) -> str:
    rule = str(c.get("rule") or "unknown")
    classification = str(c.get("classification") or "unknown")
    raw_files = c.get("files") or []
    files_count = c.get("files_touched")
    if files_count is None:
        files_count = len(raw_files) if isinstance(raw_files, list | tuple) else 0
    lines = c.get("changed_lines_total", 0)
    outside = c.get("changed_lines_outside_diff", 0)
    risk = c.get("risk", 0)
    base = (
        f"[{rule}] {classification}: {files_count} files, "
        f"{lines} lines, {outside} outside-diff, risk={risk}"
    )
    patch_path = c.get("patch_path")
    if classification == "escrow" and patch_path:
        return f"{base}. Patch staged at {patch_path}; review before applying."
    if classification == "auto":
        return f"{base}. Apply with `interlocks fix-rule --rule={rule} --apply`."
    return base


def _escape_workflow_command_data(value: object) -> str:
    return str(value).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_workflow_command_property(value: object) -> str:
    return _escape_workflow_command_data(value).replace(":", "%3A").replace(",", "%2C")


def _fix_annotate_payload(project_root: Path, result: AnnotationResult) -> dict[str, object]:
    return {
        "command": "fix-annotate",
        "passed": True,
        "status": "annotated" if result.found else "missing",
        "source": result.source,
        "input_path": relpath(project_root, result.path),
        "found": result.found,
        "annotation_count": result.annotation_count,
        "notice": result.notice,
        "warning": result.warning,
        "skip": result.skip,
    }


def _fix_annotate_error_payload(
    project_root: Path,
    source: Source,
    path: Path,
    error: str,
) -> dict[str, object]:
    return {
        "command": "fix-annotate",
        "passed": False,
        "status": "invalid-json",
        "source": source,
        "input_path": relpath(project_root, path),
        "error": error,
    }
