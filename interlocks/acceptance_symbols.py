"""Public-symbol enumerator for the acceptance trace gate.

Walks ``cfg.src_dir`` for ``*.py`` modules, imports each, and yields the
``(module_qualname, attribute_name)`` pairs that count as the project's public
surface. The trace plugin will later compare this set against the symbols
reached by Gherkin scenarios; this module only produces the "what symbols
exist" half of the comparison.

Public attributes are top-level functions, classes, and ``staticmethod``
objects whose ``__module__`` matches the containing module (re-exports do not
count). Class methods are *not* enumerated separately — the class is the unit
of granularity, matching the budget design (D3).

Results are memoized per ``(project_root, src_dir)`` for the lifetime of the
process. The walk + imports run once per CLI invocation that touches the
budget, regardless of how many gates ask for them. Tests that mutate source
files between two calls within the same project root must invoke
:func:`_clear_cache`.
"""

from __future__ import annotations

import functools
import importlib
import inspect
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from types import ModuleType

    from interlocks.config import InterlockConfig


def iter_public_symbols(cfg: InterlockConfig) -> list[tuple[str, str]]:
    """Return ``(module_qualname, attribute_name)`` pairs for the public surface.

    Modules whose import raises (any exception, see :func:`_safe_import`) are
    skipped with a stderr nudge; the result excludes them but no exception
    propagates and the caller's exit code is unaffected.

    Result is cached per ``(project_root, src_dir)``; rerunning within the same
    process is a dict lookup. Returns a fresh ``list`` each call so callers may
    mutate freely.
    """
    project_root = cfg.project_root.resolve()
    src_dir = cfg.src_dir.resolve()
    _ensure_sys_path(project_root, src_dir)
    return list(_public_symbols_cached(project_root, src_dir))


def _clear_cache() -> None:
    """Drop the memoized symbol list. Use in tests that rewrite source mid-run."""
    _public_symbols_cached.cache_clear()


def _ensure_sys_path(project_root: Path, src_dir: Path) -> None:
    """Idempotently prepend ``src_dir`` and ``project_root`` to :data:`sys.path`.

    Runs every call so cached results don't depend on which caller arrived
    first; the operation is cheap (membership check) and safe to repeat.
    """
    src_path_str = str(src_dir)
    if src_path_str not in sys.path:
        sys.path.insert(0, src_path_str)
    project_path_str = str(project_root)
    if project_path_str not in sys.path:
        sys.path.insert(0, project_path_str)


@functools.lru_cache(maxsize=8)
def _public_symbols_cached(project_root: Path, src_dir: Path) -> tuple[tuple[str, str], ...]:
    """Walk ``src_dir`` once and return the public-symbol pairs as a tuple."""
    pairs: list[tuple[str, str]] = []
    for path in sorted(src_dir.rglob("*.py")):
        qualname = _module_qualname(path, project_root)
        if qualname is None:
            continue
        module = _safe_import(qualname)
        if module is None:
            continue
        pairs.extend(_iter_module_symbols(module, qualname))
    return tuple(pairs)


def _module_qualname(path: Path, project_root: Path) -> str | None:
    """Map a ``.py`` path to its dotted module qualname, or ``None`` to skip.

    Rules:
    - Skip files inside ``__pycache__``.
    - Skip files whose name starts with ``_`` other than ``__init__.py``.
    - Skip when any path segment (excluding the filename) starts with ``_``.
    - ``__init__.py`` resolves to its containing package qualname.
    """
    try:
        rel = path.resolve().relative_to(project_root)
    except ValueError:
        return None
    *dirs, filename = rel.parts
    if "__pycache__" in dirs:
        return None
    if any(segment.startswith("_") for segment in dirs):
        return None
    if filename == "__init__.py":
        return ".".join(dirs) if dirs else None
    stem = filename.removesuffix(".py")
    if stem.startswith("_"):
        return None
    return ".".join((*dirs, stem))


def _safe_import(qualname: str) -> ModuleType | None:
    """Import ``qualname``; on import failure log to stderr and return ``None``.

    Catches the broader ``Exception`` family rather than just ``ImportError``
    because scaffold templates and pytest-bdd-style modules can raise other
    exceptions at import-time (e.g. ``IndexError`` from ``CONFIG_STACK[-1]``
    when ``pytest_bdd.scenarios()`` runs outside a pytest session). The trace
    gate's job is to enumerate the public surface, not to validate that every
    module can be imported in arbitrary contexts.
    """
    try:
        return importlib.import_module(qualname)
    except Exception as err:
        sys.stderr.write(f"interlocks: skipping {qualname}: {err}\n")
        return None


def _iter_module_symbols(module: ModuleType, qualname: str) -> Iterator[tuple[str, str]]:
    """Yield public ``(qualname, attr)`` pairs declared in ``module``."""
    for attr in sorted(vars(module)):
        if attr.startswith("_"):
            continue
        obj = getattr(module, attr, None)
        if obj is None:
            continue
        if not _is_public_kind(obj):
            continue
        if getattr(obj, "__module__", None) != qualname:
            continue
        yield (qualname, attr)


def _is_public_kind(obj: object) -> bool:
    """True when ``obj`` is a function, class, or ``staticmethod``."""
    return inspect.isfunction(obj) or inspect.isclass(obj) or isinstance(obj, staticmethod)
