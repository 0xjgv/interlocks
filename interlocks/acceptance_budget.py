"""Acceptance budget file: load, diff, prune, sign, atomic write.

The acceptance budget records the *set* of public Python symbols not yet reached
by any Gherkin scenario. The set is monotonic: it may only shrink between gate
evaluations. This module owns the on-disk format, deterministic serialization,
the signature scheme that detects out-of-band edits, and the helpers stages and
CLI commands compose to compute / mutate budgets.

Stdlib only. Atomic writes go through :mod:`interlocks._atomic`.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from interlocks._atomic import atomic_write_bytes

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


@dataclass(frozen=True)
class Budget:
    """In-memory representation of ``.interlocks/acceptance_budget.json``.

    ``signature`` is ``None`` when the budget has been freshly minted or mutated
    (e.g. via :func:`prune_stale`) and has not yet been re-signed; callers must
    invoke :func:`compute_signature` and write the resulting digest before
    :func:`write_budget`.
    """

    version: int
    baseline_at: str
    untraced: dict[str, list[str]]
    untraced_count: int
    signature: str | None


# Fixed JSON key order for the on-disk budget. Determinism is part of the
# contract: equal in-memory budgets must yield byte-identical files.
_BUDGET_KEYS = ("version", "baseline_at", "untraced", "untraced_count", "signature")


def _normalize_untraced(untraced: dict[str, list[str]]) -> dict[str, list[str]]:
    """Return ``untraced`` with sorted module keys and sorted attr lists."""
    return {module: sorted(set(untraced[module])) for module in sorted(untraced)}


def _flatten_count(untraced: dict[str, list[str]]) -> int:
    return sum(len(attrs) for attrs in untraced.values())


def load_budget(path: Path) -> Budget | None:
    """Load a budget from ``path``. Return ``None`` when the file is absent.

    Raises :class:`json.JSONDecodeError` (or :class:`ValueError`) on malformed
    JSON; raises :class:`KeyError` when required schema fields are missing.
    The ``untraced`` mapping is normalized on load so downstream serialization
    paths can trust the canonical order.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    untraced_raw = raw["untraced"]
    untraced: dict[str, list[str]] = {
        str(module): [str(attr) for attr in attrs] for module, attrs in untraced_raw.items()
    }
    return Budget(
        version=int(raw["version"]),
        baseline_at=str(raw["baseline_at"]),
        untraced=_normalize_untraced(untraced),
        untraced_count=int(raw["untraced_count"]),
        signature=raw.get("signature"),
    )


def _coerce_traced_pair(item: object) -> tuple[str, str]:
    """Accept ``"module:attr"`` strings or ``(module, attr)`` tuples."""
    if isinstance(item, str):
        module, _, attr = item.partition(":")
        return module, attr
    if isinstance(item, tuple) and len(item) == 2:
        return str(item[0]), str(item[1])
    msg = f"unsupported traced entry: {item!r}"
    raise TypeError(msg)


def compute_untraced(
    public_symbols: Iterable[tuple[str, str]],
    traced_index: Iterable[tuple[str, str]] | Iterable[str],
) -> dict[str, list[str]]:
    """Return ``module -> sorted attrs`` for ``public_symbols - traced``.

    ``traced_index`` may arrive as flat ``"module:attr"`` strings (the storage
    form in ``trace.json.traced_symbols_index``) or as ``(module, attr)``
    tuples. Both are coerced.
    """
    public_set: set[tuple[str, str]] = {(str(m), str(a)) for m, a in public_symbols}
    traced_set: set[tuple[str, str]] = {_coerce_traced_pair(item) for item in traced_index}
    untraced_pairs = public_set - traced_set
    untraced: dict[str, list[str]] = {}
    for module, attr in untraced_pairs:
        untraced.setdefault(module, []).append(attr)
    return _normalize_untraced(untraced)


def prune_stale(budget: Budget, public_symbols: Iterable[tuple[str, str]]) -> Budget:
    """Drop budget entries whose ``(module, attr)`` no longer exists in the source.

    Returns a new :class:`Budget` with ``untraced`` filtered, ``untraced_count``
    recomputed, and ``signature`` cleared to ``None`` so the caller is forced to
    re-sign before writing.
    """
    public_set: set[tuple[str, str]] = {(str(m), str(a)) for m, a in public_symbols}
    pruned: dict[str, list[str]] = {}
    for module, attrs in budget.untraced.items():
        kept = [attr for attr in attrs if (module, attr) in public_set]
        if kept:
            pruned[module] = kept
    pruned = _normalize_untraced(pruned)
    return replace(
        budget,
        untraced=pruned,
        untraced_count=_flatten_count(pruned),
        signature=None,
    )


def _serialize_budget(budget: Budget) -> bytes:
    """Render ``budget`` to bytes with a fixed key order and sorted contents."""
    untraced = _normalize_untraced(budget.untraced)
    payload: dict[str, object] = {
        "version": budget.version,
        "baseline_at": budget.baseline_at,
        "untraced": untraced,
        "untraced_count": budget.untraced_count,
        "signature": budget.signature,
    }
    ordered = {key: payload[key] for key in _BUDGET_KEYS}
    text = json.dumps(ordered, indent=2, ensure_ascii=False, sort_keys=False)
    return (text + "\n").encode("utf-8")


def write_budget(path: Path, budget: Budget) -> None:
    """Atomically write ``budget`` to ``path`` with deterministic ordering."""
    atomic_write_bytes(path, _serialize_budget(budget))


def _canonical_signed_payload(budget: Budget) -> bytes:
    """Bytes hashed by :func:`compute_signature` (signature field excluded)."""
    untraced = _normalize_untraced(budget.untraced)
    payload = {
        "version": budget.version,
        "baseline_at": budget.baseline_at,
        "untraced": untraced,
        "untraced_count": budget.untraced_count,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def compute_signature(budget: Budget, repo_secret: str) -> str:
    """Return ``"sha256:" + hex`` digest binding the budget contents to the repo.

    The hash input is canonical JSON of ``{version, baseline_at, untraced,
    untraced_count}`` (sorted keys, no whitespace) concatenated with
    ``repo_secret``. The stored ``signature`` field is excluded so signing is
    idempotent.
    """
    digest = hashlib.sha256(_canonical_signed_payload(budget) + repo_secret.encode("utf-8"))
    return "sha256:" + digest.hexdigest()


def verify_signature(budget: Budget, repo_secret: str) -> Literal["ok", "missing", "mismatch"]:
    """Compare the budget's stored signature against a fresh recomputation."""
    if not budget.signature:
        return "missing"
    expected = compute_signature(budget, repo_secret)
    return "ok" if expected == budget.signature else "mismatch"


def derive_repo_secret(project_root: Path) -> str:
    """Return the repo-deterministic secret used to sign the budget.

    Reads ``[project].name`` (or the legacy ``[tool.poetry].name`` fallback)
    from ``project_root / "pyproject.toml"``. Per-project, stable across
    commits, releases, and shallow clones — git is **not** consulted because
    ``actions/checkout`` defaults to depth=1 and rewrites obscure the true
    first-commit hash. Falls back to
    ``f"interlocks-acceptance-budget:{project_root.resolve()}"`` when the file
    is absent, malformed, or missing a recognizable name.
    """
    fallback = f"interlocks-acceptance-budget:{project_root.resolve()}"
    pyproject = project_root / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return fallback
    project = data.get("project")
    if isinstance(project, dict):
        name = project.get("name")
        if isinstance(name, str) and name.strip():
            return f"interlocks-acceptance-budget:{name.strip()}"
    poetry = data.get("tool", {}).get("poetry") if isinstance(data.get("tool"), dict) else None
    if isinstance(poetry, dict):
        name = poetry.get("name")
        if isinstance(name, str) and name.strip():
            return f"interlocks-acceptance-budget:{name.strip()}"
    return fallback


__all__ = [
    "Budget",
    "compute_signature",
    "compute_untraced",
    "derive_repo_secret",
    "load_budget",
    "prune_stale",
    "verify_signature",
    "write_budget",
]
