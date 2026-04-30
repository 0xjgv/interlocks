"""Shared readers for cached quality signals (coverage.xml, lizard, mutmut)."""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from interlocks.runner import capture, generate_coverage_xml, python_m, tool

if TYPE_CHECKING:
    from collections.abc import Iterator

_LIZARD_LINE = re.compile(r"^\s*(\d+)\s+(\d+)\s+\d+\s+(\d+)\s+\d+\s+(\S+)@(\d+)-(\d+)@(.+)$")

PY_SKIP_DIRS = frozenset({".venv", "venv", "__pycache__", ".tox", "node_modules"})


def iter_py_files(root: Path) -> Iterator[Path]:
    """Yield .py files under ``root``, pruning ``PY_SKIP_DIRS`` at descent."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in PY_SKIP_DIRS]
        for name in filenames:
            if name.endswith(".py"):
                yield Path(dirpath) / name


def newer_than(path: Path, mtime: float) -> bool:
    try:
        return path.stat().st_mtime > mtime
    except OSError:
        return False


@dataclass(frozen=True)
class FunctionStats:
    """One row from lizard's `-w`-ish text output (NLOC, CCN, args, loc range, path)."""

    path: str
    name: str
    start: int
    end: int
    nloc: int
    ccn: int
    args: int

    @property
    def loc(self) -> int:
        return self.end - self.start + 1


@dataclass(frozen=True)
class CrapRow:
    """CRAP metric plus its inputs for one function (keyed by path + loc range)."""

    path: str
    name: str
    start: int
    end: int
    ccn: int
    loc: int
    coverage: float
    crap: float


@dataclass(frozen=True)
class MutationSummary:
    """Parsed `mutmut results --all=true` output. ``completed`` is unknowable here."""

    killed: int
    survived: int
    timeout: int
    score: float
    survivors: list[str] = field(default_factory=list)


def _source_prefix(root: ET.Element) -> str:
    """Return a ``cwd``-relative prefix for ``<sources><source>`` (or "")."""
    for src in root.findall("sources/source"):
        text = (src.text or "").strip()
        if not text:
            continue
        try:
            rel = Path(text).resolve().relative_to(Path.cwd().resolve())
        except ValueError:
            continue
        return rel.as_posix()
    return ""


def parse_coverage(cov_file: Path) -> dict[str, dict[int, int]]:
    """Return {filename: {lineno: hits}} keyed by cwd-relative paths.

    coverage.xml stores filenames relative to ``<source>`` (e.g. ``cli.py`` when
    source is ``interlocks/``). Prefix with the source dir so keys match the
    ``interlocks/cli.py`` paths lizard emits.
    """
    root = ET.parse(cov_file).getroot()
    prefix = _source_prefix(root)
    cov_map: dict[str, dict[int, int]] = {}
    for cls in root.iter("class"):
        fn = cls.get("filename", "")
        key = f"{prefix}/{fn}" if prefix and not fn.startswith(prefix + "/") else fn
        cov_map[key] = {
            int(ln.get("number", "0")): int(ln.get("hits", "0"))
            for ln in cls.iter("line")
            if ln.get("number")
        }
    return cov_map


def coverage_line_rate(cov_file: Path | None = None) -> float | None:
    """Overall coverage.xml line-rate (0..1), or None if unreadable.

    When ``cov_file`` is omitted, regenerate ``coverage.xml`` from ``.coverage``
    (skips silently if ``.coverage`` is absent).
    """
    if cov_file is None:
        if not Path(".coverage").exists():
            return None
        cov_file = generate_coverage_xml()
    try:
        root = ET.parse(cov_file).getroot()
    except (ET.ParseError, FileNotFoundError):
        return None
    rate = root.get("line-rate")
    return float(rate) if rate is not None else None


def function_coverage(lines: dict[int, int], start: int, end: int) -> float:
    """Fraction of executable lines between ``start``/``end`` that were hit."""
    in_range = [n for n in range(start, end + 1) if n in lines]
    return (sum(1 for n in in_range if lines[n] > 0) / len(in_range)) if in_range else 0.0


def lizard_functions(src_arg: str) -> list[FunctionStats]:
    """Invoke lizard on ``src_arg`` and return parsed function rows."""
    res = capture(tool("lizard", src_arg))
    return _parse_lizard(res.stdout)


def _parse_lizard(stdout: str) -> list[FunctionStats]:
    rows: list[FunctionStats] = []
    for line in stdout.splitlines():
        m = _LIZARD_LINE.match(line)
        if not m:
            continue
        nloc_s, ccn_s, args_s, name, start_s, end_s, path = m.groups()
        rows.append(
            FunctionStats(
                path=path,
                name=name,
                start=int(start_s),
                end=int(end_s),
                nloc=int(nloc_s),
                ccn=int(ccn_s),
                args=int(args_s),
            )
        )
    return rows


def compute_crap_rows(
    fns: list[FunctionStats],
    cov_map: dict[str, dict[int, int]],
    *,
    max_crap: float | None = None,
    changed: set[str] | None = None,
) -> list[CrapRow]:
    """Join lizard functions with coverage to produce CRAP rows.

    When ``max_crap`` is ``None``, returns every row (reader mode — used by
    ``interlocks trust``). When set, returns only rows whose CRAP exceeds the
    threshold (gate mode — used by ``interlocks crap``). ``changed``, when given,
    filters to functions in those paths.
    """
    rows: list[CrapRow] = []
    for fn in fns:
        if changed is not None and fn.path not in changed:
            continue
        lines = cov_map.get(fn.path) or cov_map.get(fn.path.lstrip("./")) or {}
        cov = function_coverage(lines, fn.start, fn.end)
        crap = fn.ccn * fn.ccn * (1 - cov) ** 3 + fn.ccn
        if max_crap is not None and crap <= max_crap:
            continue
        rows.append(
            CrapRow(
                path=fn.path,
                name=fn.name,
                start=fn.start,
                end=fn.end,
                ccn=fn.ccn,
                loc=fn.loc,
                coverage=cov,
                crap=crap,
            )
        )
    return rows


def read_mutation_summary() -> MutationSummary | None:
    """Return a parsed mutation summary from ``mutmut results --all=true``.

    Returns ``None`` when no mutmut output directory exists (no prior run).
    Does not run mutation — only reads cached results.
    """
    if not any(Path(p).is_dir() for p in ("mutants", ".mutmut-cache")):
        return None
    res = capture([*python_m("mutmut"), "results", "--all=true"])
    by_status = _parse_results(res.stdout)
    killed = len(by_status.get("killed", []))
    survived = by_status.get("survived", [])
    timeout = len(by_status.get("timeout", []))
    total = killed + len(survived) + timeout
    score = (killed / total * 100) if total else 0.0
    return MutationSummary(
        killed=killed,
        survived=len(survived),
        timeout=timeout,
        score=score,
        survivors=survived,
    )


def _parse_results(stdout: str) -> dict[str, list[str]]:
    """Group mutant keys by status from `mutmut results --all=true` output."""
    by_status: dict[str, list[str]] = {}
    for line in stdout.splitlines():
        key, sep, status = line.strip().partition(": ")
        if not sep or "__mutmut_" not in key:
            continue
        by_status.setdefault(status, []).append(key)
    return by_status
