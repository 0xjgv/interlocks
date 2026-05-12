"""Apply + verify path for the rule-scoped harness.

``apply_with_verify`` snapshots target files, applies the rule, runs the
verifier, and restores the snapshot if verification fails — preserving the
``--apply`` invariant that the tree only mutates on a clean verify.
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
