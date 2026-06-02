"""Shared readers for cached quality signals (coverage.xml, lizard, mutmut)."""

from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from typing import TYPE_CHECKING

from interlocks.config import load_config
from interlocks.runner import capture, generate_coverage_xml, uv_run_with, uvx_tool

if TYPE_CHECKING:
    from collections.abc import Iterator

    from interlocks.config import InterlockConfig

_LIZARD_LINE = re.compile(
    r"^\s*(?P<nloc>\d+)\s+(?P<ccn>\d+)\s+\d+\s+(?P<args>\d+)\s+\d+\s+"
    r"(?P<name>\S+)@(?P<start>\d+)-(?P<end>\d+)@(?P<path>.+)$"
)

PY_SKIP_DIRS = frozenset({".venv", "venv", "__pycache__", ".tox", "node_modules"})
MUTATION_EVIDENCE = Path(".interlocks/mutation.json")
_MUTMUT_STATS_FILES = (
    Path("mutants/mutmut-stats.json"),
    Path(".mutmut-cache/mutmut-stats.json"),
)


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


def coverage_inputs(cfg: InterlockConfig) -> Iterator[Path]:
    """Yield files whose edits make cached coverage evidence stale."""
    yield cfg.project_root / "pyproject.toml"
    for root in (cfg.src_dir, cfg.test_dir, cfg.properties_dir):
        if root is None:
            continue
        if root.is_file() and root.suffix == ".py":
            yield root
        elif root.is_dir():
            yield from iter_py_files(root)


def coverage_cache_is_stale(cov_cache: Path, cfg: InterlockConfig) -> bool:
    try:
        cov_mtime = cov_cache.stat().st_mtime
    except OSError:
        return True
    return any(newer_than(path, cov_mtime) for path in coverage_inputs(cfg))


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
    """Parsed `mutmut results --all=true` output plus Interlocks evidence metadata."""

    killed: int
    survived: int
    timeout: int
    score: float
    survivors: list[str] = field(default_factory=list)
    completed: bool | None = None


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
        lines: dict[int, int] = {}
        for line in cls.iter("line"):
            parsed = _coverage_line_entry(line)
            if parsed is not None:
                number, hits = parsed
                lines[number] = hits
        cov_map[key] = lines
    return cov_map


def _coverage_line_entry(line: ET.Element) -> tuple[int, int] | None:
    raw_number = line.get("number")
    if not raw_number:
        return None
    raw_hits = line.get("hits")
    try:
        number = int(raw_number)
        hits = int(raw_hits) if raw_hits is not None else 0
    except ValueError:
        return None
    return number, hits


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
    if rate is None:
        return None
    try:
        parsed = float(rate)
    except ValueError:
        return None
    return parsed if isfinite(parsed) and 0.0 <= parsed <= 1.0 else None


def function_coverage(lines: dict[int, int], start: int, end: int) -> float:
    """Fraction of executable lines between ``start``/``end`` that were hit."""
    hits = [hit for number, hit in lines.items() if start <= number <= end]
    return (sum(1 for hit in hits if hit > 0) / len(hits)) if hits else 0.0


def lizard_functions(src_arg: str) -> list[FunctionStats]:
    """Invoke lizard on ``src_arg`` and return parsed function rows."""
    cfg = load_config()
    res = capture(uvx_tool("lizard", src_arg, version=cfg.tool_version("lizard")))
    return _parse_lizard(res.stdout)


def _parse_lizard(stdout: str) -> list[FunctionStats]:
    rows: list[FunctionStats] = []
    for line in stdout.splitlines():
        # lizard re-lists every CCN>15 function under a trailing warnings block.
        # Stop at its header so high-complexity functions aren't counted twice.
        if line.startswith("!!!!") and "Warnings" in line:
            break
        m = _LIZARD_LINE.match(line)
        if not m:
            continue
        rows.append(
            FunctionStats(
                path=m["path"],
                name=m["name"],
                start=int(m["start"]),
                end=int(m["end"]),
                nloc=int(m["nloc"]),
                ccn=int(m["ccn"]),
                args=int(m["args"]),
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
    threshold (gate mode — used by ``interlocks gate crap``). ``changed``, when given,
    filters to functions in those paths.
    """
    rows: list[CrapRow] = []
    for fn in fns:
        if changed is not None and fn.path not in changed:
            continue
        stripped_path = fn.path.lstrip("./")
        lines = cov_map[fn.path] if fn.path in cov_map else cov_map.get(stripped_path, {})
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


def read_mutation_summary(*, require_interlocks_evidence: bool = True) -> MutationSummary | None:
    """Return a parsed mutation summary from ``mutmut results --all=true``.

    Returns ``None`` when no mutmut output directory exists (no prior run), or
    when the latest mutmut stats were not produced by ``interlocks gate mutation``.
    Does not run mutation; only reads cached results.
    """
    if not any(Path(p).is_dir() for p in ("mutants", ".mutmut-cache")):
        return None
    cfg = load_config()
    project_root = getattr(cfg, "project_root", Path.cwd())
    evidence = _current_mutation_evidence(project_root) if require_interlocks_evidence else None
    if require_interlocks_evidence and evidence is None:
        return None
    res = capture(
        uv_run_with(
            "interlocks-mutmut",
            "python",
            "-m",
            "mutmut",
            "results",
            "--all=true",
            version=cfg.tool_version("interlocks-mutmut"),
        )
    )
    if getattr(res, "returncode", 0) != 0:
        return None
    by_status = _parse_results(res.stdout)
    killed = len(by_status.get("killed", []))
    survived = by_status.get("survived", [])
    timeout = len(by_status.get("timeout", []))
    total = killed + len(survived) + timeout
    if total == 0:
        return None
    score = killed / total * 100
    return MutationSummary(
        killed=killed,
        survived=len(survived),
        timeout=timeout,
        score=score,
        survivors=survived,
        completed=_mutation_evidence_completed(evidence),
    )


def _has_current_mutation_evidence(project_root: Path) -> bool:
    return _current_mutation_evidence(project_root) is not None


def read_mutation_evidence(project_root: Path | None = None) -> dict[str, object] | None:
    """Return current Interlocks mutation evidence without running mutmut."""
    root = project_root or getattr(load_config(), "project_root", Path.cwd())
    return _current_mutation_evidence(root)


def mutation_evidence_no_results(evidence: dict[str, object] | None) -> bool:
    """True when the latest Interlocks mutation run produced no checked result rows."""
    return evidence is not None and evidence.get("no_results") is True


def mutation_evidence_is_stale(project_root: Path) -> bool:
    evidence = project_root / MUTATION_EVIDENCE
    if not evidence.is_file():
        return False
    stats_mtime = _newest_existing_mtime(project_root / path for path in _MUTMUT_STATS_FILES)
    if stats_mtime is None:
        return False
    try:
        evidence_mtime = evidence.stat().st_mtime
    except OSError:
        return False
    return evidence_mtime < stats_mtime


def _current_mutation_evidence(project_root: Path) -> dict[str, object] | None:
    evidence = project_root / MUTATION_EVIDENCE
    if not evidence.is_file():
        return None
    if mutation_evidence_is_stale(project_root):
        return None
    try:
        payload = json.loads(evidence.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _mutation_evidence_completed(evidence: dict[str, object] | None) -> bool | None:
    if evidence is None:
        return None
    completed = evidence.get("completed")
    return completed if isinstance(completed, bool) else None


def _newest_existing_mtime(paths: Iterator[Path]) -> float | None:
    newest: float | None = None
    for path in paths:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        newest = mtime if newest is None else max(newest, mtime)
    return newest


def _parse_results(stdout: str) -> dict[str, list[str]]:
    """Group mutant keys by status from `mutmut results --all=true` output."""
    by_status: dict[str, list[str]] = {}
    for line in stdout.splitlines():
        key, sep, status = line.strip().partition(": ")
        if not sep or "__mutmut_" not in key:
            continue
        by_status.setdefault(status, []).append(key)
    return by_status
