"""Apply + verify path for the rule-scoped harness.

``apply_with_verify`` snapshots target files, applies the rule, runs the
verifier, and restores the snapshot if verification fails — preserving the
``--apply`` invariant that the tree only mutates on a clean verify.
``apply_many_with_verify`` extends the same invariant to multi-rule batches
selected by the optimizer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from interlocks.lintfix.simulate import apply_rule
from interlocks.runner import capture

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class VerifyResult:
    applied: bool
    returncode: int
    stdout: str
    stderr: str
    restored: bool


@dataclass(frozen=True)
class BatchVerifyResult:
    """Outcome of a multi-rule apply + verify.

    ``applied_rules`` is the prefix that mutated the tree before a failure
    triggered the restore (or the full set, on success). ``failed_rule`` is
    set when ruff itself crashed on one of the rules and the batch aborted
    before reaching the verifier.
    """

    applied: bool
    returncode: int
    stdout: str
    stderr: str
    restored: bool
    applied_rules: tuple[str, ...]
    failed_rule: str | None = None


def apply_with_verify(
    *, rule: str, files: tuple[str, ...], verify_cmd: Sequence[str]
) -> VerifyResult:
    """Apply ``rule`` to ``files`` in the working tree; restore on verifier failure."""
    snapshot = _snapshot(files)
    apply_result = apply_rule(rule, files)
    # ruff `--fix` returns 0 on success even when violations remained advisory;
    # rc>=2 means ruff itself crashed and we should not run the verifier.
    if apply_result.returncode >= 2:
        _restore(snapshot)
        return VerifyResult(
            False,
            apply_result.returncode,
            apply_result.stdout,
            apply_result.stderr,
            restored=True,
        )
    result = capture(list(verify_cmd))
    if result.returncode == 0:
        return VerifyResult(True, 0, result.stdout, result.stderr, restored=False)
    _restore(snapshot)
    return VerifyResult(False, result.returncode, result.stdout, result.stderr, restored=True)


def apply_many_with_verify(
    *,
    rules_and_files: Sequence[tuple[str, tuple[str, ...]]],
    verify_cmd: Sequence[str],
) -> BatchVerifyResult:
    """Apply each ``(rule, files)`` in order; verify once; restore on any failure.

    The snapshot covers the union of all touched files so a partial-apply
    failure rolls back the entire batch — never just the most recent rule.
    """
    if not rules_and_files:
        return BatchVerifyResult(True, 0, "", "", restored=False, applied_rules=())
    all_files = tuple({f for _, files in rules_and_files for f in files})
    snapshot = _snapshot(all_files)
    applied: list[str] = []
    for rule, files in rules_and_files:
        apply_result = apply_rule(rule, files)
        if apply_result.returncode >= 2:
            _restore(snapshot)
            return BatchVerifyResult(
                applied=False,
                returncode=apply_result.returncode,
                stdout=apply_result.stdout,
                stderr=apply_result.stderr,
                restored=True,
                applied_rules=tuple(applied),
                failed_rule=rule,
            )
        applied.append(rule)
    result = capture(list(verify_cmd))
    if result.returncode == 0:
        return BatchVerifyResult(
            applied=True,
            returncode=0,
            stdout=result.stdout,
            stderr=result.stderr,
            restored=False,
            applied_rules=tuple(applied),
        )
    _restore(snapshot)
    return BatchVerifyResult(
        applied=False,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        restored=True,
        applied_rules=tuple(applied),
    )


def _snapshot(files: tuple[str, ...]) -> dict[str, bytes]:
    snap: dict[str, bytes] = {}
    for f in files:
        path = Path(f)
        try:
            snap[f] = path.read_bytes()
        except OSError:
            continue
    return snap


def _restore(snapshot: dict[str, bytes]) -> None:
    for f, data in snapshot.items():
        try:
            Path(f).write_bytes(data)
        except OSError:
            continue
