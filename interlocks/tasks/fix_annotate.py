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
from interlocks.config import load_config
from interlocks.lintfix import escrow
from interlocks.runner import arg_value

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from interlocks.lintfix.rules import Mode

Severity = Literal["notice", "warning"]
Source = Literal["plan", "optimize"]

_SEVERITY: dict[Mode, Severity] = {
    "auto": "notice",
    "escrow": "notice",
    "advisory": "warning",
}


def cmd_fix_annotate(*, source: Source | None = None, input_path: str | None = None) -> None:
    """Emit GitHub Actions annotations for the fix plan.

    ``source`` selects the JSON file under ``.lintfix/``; ``input_path`` overrides it.
    """
    src: Source = source or _arg_source()
    input_arg = input_path if input_path is not None else arg_value("--input=", "")

    cfg = load_config()
    path = _resolve_path(cfg.project_root, src, input_arg)
    if not path.is_file():
        ui.row("fix-annotate", "(no plan)", "ok", detail=cfg.relpath(path), state="ok")
        return

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        ui.row("fix-annotate", "parse", str(exc), state="fail")
        sys.exit(2)

    counts = {"notice": 0, "warning": 0, "skip": 0}
    for c in _iter_candidates(payload, src):
        if c.get("classification") == "skip":
            counts["skip"] += 1
            continue
        for ann in _annotations_for(c):
            print(ann.line)
            counts[ann.severity] += 1

    ui.section("fix-annotate")
    ui.kv_block([
        ("source", cfg.relpath(path)),
        ("notice", str(counts["notice"])),
        ("warning", str(counts["warning"])),
        ("skip", str(counts["skip"])),
    ])


def _arg_source() -> Source:
    value = arg_value("--source=", "plan")
    if value not in ("plan", "optimize"):
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
            for c in payload.get(key, []):
                yield _flatten_optimize(c)
        return
    yield from payload.get("candidates", [])


def _flatten_optimize(c: dict[str, Any]) -> dict[str, Any]:
    """Map optimize-source fields onto the flat plan schema used by the formatter."""
    cost = c.get("cost") or {}
    return {
        **c,
        "classification": c["policy_mode"],
        "files_touched": cost.get("files", len(c.get("files") or [])),
        "changed_lines_total": cost.get("changed_lines", 0),
        "changed_lines_outside_diff": cost.get("outside_diff", 0),
        "risk": cost.get("risk", 0),
    }


@dataclass(frozen=True, slots=True)
class _Annotation:
    line: str
    severity: Severity


def _annotations_for(c: dict[str, Any]) -> Iterable[_Annotation]:
    severity = _SEVERITY.get(c["classification"])
    if severity is None:
        return
    message = _format_message(c)
    files = c.get("files") or []
    if not files:
        yield _Annotation(f"::{severity}::{message}", severity)
        return
    for file_path in files:
        yield _Annotation(f"::{severity} file={file_path},line=1::{message}", severity)


def _format_message(c: dict[str, Any]) -> str:
    rule = c["rule"]
    classification = c["classification"]
    files_count = c.get("files_touched") or len(c.get("files") or [])
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
