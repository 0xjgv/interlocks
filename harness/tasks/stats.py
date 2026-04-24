"""Trust-score report — aggregates cached quality signals into one verdict."""

from __future__ import annotations

import ast
import datetime as _dt
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

from harness import ui
from harness.config import load_config
from harness.git import changed_py_files_vs
from harness.metrics import (
    CrapRow,
    MutationSummary,
    compute_crap_rows,
    iter_py_files,
    lizard_functions,
    parse_coverage,
    read_mutation_summary,
)
from harness.runner import GREEN, RED, RESET, VERBOSE, YELLOW, generate_coverage_xml, warn_skip
from harness.tasks.coverage import cmd_coverage

if TYPE_CHECKING:
    from harness.config import HarnessConfig


SUSPICIOUS_MIN_LOC = 5
CRAP_OVERRUN_WEIGHT = 2.0
CRAP_MAX_PENALTY = 30.0
MUTATION_MAX_PENALTY = 30.0
COVERAGE_MAX_PENALTY = 20.0
SUSPICIOUS_PENALTY_EACH = 3.0
TRUST_HISTORY_CAP = 20
TRUST_GREEN = 85
TRUST_YELLOW = 65
CRAP_RED_MARGIN = 5.0

# (min_score, color, emoji, word) — highest tier first; the first match wins.
_TIERS: tuple[tuple[float, str, str, str], ...] = (
    (TRUST_GREEN, GREEN, "🟢", "HEALTHY"),
    (TRUST_YELLOW, YELLOW, "🟡", "CAUTION"),
    (0.0, RED, "🔴", "RISKY"),
)


@dataclass(frozen=True)
class TestInspection:
    """One `test_*` function (or TestCase method) with assert-shape stats."""

    # Opt out of pytest's test-class collection (our name starts with "Test").
    __test__ = False

    file: str
    name: str
    loc: int
    assert_count: int
    trivial_asserts: int


@dataclass
class TrustReport:
    """Aggregated signals for one stats run."""

    score: float
    prev_score: float | None
    crap_rows: list[CrapRow]
    suspicious: list[TestInspection]
    mutation: MutationSummary | None
    coverage_pct: float | None
    crap_max: float
    diff_changed: set[str] = field(default_factory=set)
    diff_new_crap: list[CrapRow] = field(default_factory=list)


# ─────────────── trust formula ──────────────────────────────────


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _compute_trust(
    *,
    crap_rows: list[CrapRow],
    mutation: MutationSummary | None,
    coverage_pct: float | None,
    suspicious_count: int,
    cfg: HarnessConfig,
) -> float:
    """Start at 100, subtract capped penalties for each signal. Floor at 0."""
    score = 100.0
    max_crap = max((r.crap for r in crap_rows), default=0.0)
    overrun = max(0.0, max_crap - cfg.crap_max)
    score -= _clamp(overrun * CRAP_OVERRUN_WEIGHT, 0, CRAP_MAX_PENALTY)
    if mutation is not None:
        shortfall = cfg.mutation_min_score - mutation.score
        score -= _clamp(shortfall, 0, MUTATION_MAX_PENALTY)
    if coverage_pct is not None:
        cov_shortfall = cfg.coverage_min - coverage_pct
        score -= _clamp(cov_shortfall, 0, COVERAGE_MAX_PENALTY)
    score -= suspicious_count * SUSPICIOUS_PENALTY_EACH
    return max(score, 0.0)


def _tier(score: float) -> tuple[float, str, str, str]:
    return next(t for t in _TIERS if score >= t[0])


def _emoji(score: float) -> str:
    return _tier(score)[2]


# ─────────────── AST walker: assertion-light tests ──────────────

# Python calls into these types introduce a new scope — their body's asserts
# belong to the nested callable, not the enclosing test.
_SCOPE_BOUNDARIES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _is_trivial(expr: ast.expr | None) -> bool:
    """``None`` (empty ``self.assertTrue()``) or a literal → no real check."""
    return expr is None or isinstance(expr, ast.Constant)


def _iter_same_scope(node: ast.AST) -> Iterator[ast.AST]:
    """Yield descendants without crossing into nested function/lambda scopes.

    ``ast.walk`` recurses into inner ``def``/``lambda`` bodies, which would
    credit helper-function asserts to the enclosing test and hide tests that
    only call a helper (the assertion-light case we want to detect).
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _SCOPE_BOUNDARIES):
            continue
        yield child
        yield from _iter_same_scope(child)


def _collect_test_inspections(
    test_dir: Path, cfg: HarnessConfig | None = None
) -> list[TestInspection]:
    """Walk ``test_dir`` for `test_*` fns + TestCase methods; return assert stats."""
    if not test_dir.is_dir():
        return []
    relpath = cfg.relpath if cfg is not None else str
    out: list[TestInspection] = []
    for path in sorted(iter_py_files(test_dir)):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        out.extend(_inspect_tree(tree, relpath(path)))
    return out


def _inspect_tree(tree: ast.Module, rel_path: str) -> list[TestInspection]:
    rows: list[TestInspection] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            rows.append(_inspect_function(node, rel_path, qualname=node.name))
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name.startswith("test_"):
                    rows.append(
                        _inspect_function(item, rel_path, qualname=f"{node.name}.{item.name}")
                    )
    return rows


def _inspect_function(fn: ast.FunctionDef, rel_path: str, *, qualname: str) -> TestInspection:
    asserts = 0
    trivial = 0
    for child in _iter_same_scope(fn):
        if isinstance(child, ast.Assert):
            asserts += 1
            trivial += _is_trivial(child.test)
        elif isinstance(child, ast.Call) and _is_self_assert_call(child):
            asserts += 1
            first = child.args[0] if child.args else None
            trivial += _is_trivial(first)
    end_line = fn.end_lineno or fn.lineno
    return TestInspection(
        file=rel_path,
        name=qualname,
        loc=end_line - fn.lineno + 1,
        assert_count=asserts,
        trivial_asserts=trivial,
    )


def _is_self_assert_call(call: ast.Call) -> bool:
    """Match `self.assertXxx(...)` / `cls.assertXxx(...)` unittest-style calls."""
    func = call.func
    if not isinstance(func, ast.Attribute) or not func.attr.startswith("assert"):
        return False
    return isinstance(func.value, ast.Name) and func.value.id in {"self", "cls"}


def _flag_suspicious(inspections: list[TestInspection]) -> list[TestInspection]:
    """Flag tests with LOC > floor AND (no asserts OR every assert trivial)."""
    return [
        t
        for t in inspections
        if t.loc > SUSPICIOUS_MIN_LOC and t.assert_count in (0, t.trivial_asserts)
    ]


# ─────────────── trend cache ────────────────────────────────────


def _cache_path(project_root: Path) -> Path:
    return project_root / ".harness" / "trust.json"


def _load_history(cache: Path) -> list[dict[str, object]]:
    if not cache.is_file():
        return []
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    history = data.get("history")
    if not isinstance(history, list):
        return []
    return [h for h in history if isinstance(h, dict)]


def _read_prev_trust(cache: Path) -> float | None:
    """Return the previous run's trust score, or None on miss/corruption."""
    history = _load_history(cache)
    if not history:
        return None
    score = history[-1].get("score")
    return float(score) if isinstance(score, (int, float)) else None


def _write_trust(cache: Path, score: float) -> None:
    """Append a new entry and trim to the last ``TRUST_HISTORY_CAP`` runs."""
    cache.parent.mkdir(parents=True, exist_ok=True)
    history = _load_history(cache)
    history.append({
        "score": round(score, 1),
        "ts": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
    })
    history = history[-TRUST_HISTORY_CAP:]
    cache.write_text(json.dumps({"history": history}, indent=2) + "\n", encoding="utf-8")


# ─────────────── render ─────────────────────────────────────────


def _render(report: TrustReport, *, verbose: bool) -> None:
    """Render a trust report using the same section grammar as stage output."""
    _render_header(report)
    _render_suspicious(report.suspicious, verbose=verbose)
    _render_hot_files(report.crap_rows, crap_max=report.crap_max, verbose=verbose)
    _render_diff(report)
    _render_next_actions(report, verbose=verbose)
    _render_stages(report)


def _render_header(report: TrustReport) -> None:
    _, color, emoji, word = _tier(report.score)
    score_txt = f"{color}{report.score:.0f}/100{RESET}"
    delta_txt = ""
    if report.prev_score is not None:
        delta = report.score - report.prev_score
        delta_txt = f"  {_delta_arrow(delta)} {delta:+.1f} since last run"
    sentence = _verdict_sentence(
        suspicious_count=len(report.suspicious),
        crap_count=len(report.crap_rows),
        mutation=report.mutation,
    )
    ui.section("Trust")
    ui.kv_block([
        ("score", f"{score_txt}{delta_txt}  {emoji} {word}"),
        ("verdict", sentence),
    ])


def _print_truncated(rows: list, *, verbose: bool, formatter: Callable[..., str]) -> None:
    """Print a section body: each row via ``formatter``, with an overflow hint."""
    if not rows:
        print("    (none)")
        return
    shown = rows if verbose else rows[:10]
    for row in shown:
        print(formatter(row))
    if not verbose and len(rows) > len(shown):
        print(f"    … {len(rows) - len(shown)} more (use --verbose)")


def _format_suspicious(t: TestInspection) -> str:
    detail = "0 asserts" if t.assert_count == 0 else f"{t.assert_count} assert(s) (trivial)"
    return f"    {t.file}::{t.name}  {t.loc} LOC, {detail}"


def _render_suspicious(rows: list[TestInspection], *, verbose: bool) -> None:
    ui.section("Suspicious Tests")
    print("  assertion-light, LOC > 5")
    _print_truncated(rows, verbose=verbose, formatter=_format_suspicious)


def _render_hot_files(rows: list[CrapRow], *, crap_max: float, verbose: bool) -> None:
    ui.section("Hot Files")
    print("  CRAP > configured ceiling")

    def _format(r: CrapRow) -> str:
        color = _crap_color(r.crap, crap_max)
        return (
            f"    {r.path}::{r.name}  CCN {r.ccn}  "
            f"cov {r.coverage * 100:.0f}%  "
            f"{color}CRAP {r.crap:.1f}{RESET}"
        )

    _print_truncated(rows, verbose=verbose, formatter=_format)


def _render_diff(report: TrustReport) -> None:
    ui.section("Diff")
    if not report.diff_changed:
        print("    (none)")
        return
    print(f"  since HEAD~1: {len(report.diff_changed)} changed file(s)")
    hot_paths = {r.path for r in report.diff_new_crap}
    for path in sorted(report.diff_changed)[:10]:
        marker = "  (new CRAP>ceiling fn)" if path in hot_paths else ""
        print(f"    {path}{marker}")


def _render_next_actions(report: TrustReport, *, verbose: bool) -> None:
    ui.section("Next Actions")
    if not report.suspicious and not report.crap_rows:
        print("    (none)")
        return
    if report.suspicious:
        _render_suspicious_actions(report.suspicious, verbose=verbose)
    if report.crap_rows:
        _render_crap_actions(report.crap_rows, verbose=verbose)
    print("    Refresh with `harness trust --refresh --no-trend` or `harness ci`.")


def _render_suspicious_actions(rows: list[TestInspection], *, verbose: bool) -> None:
    print("    Add behavioral assertions, or shorten/mark intentional smoke tests:")
    shown = rows if verbose else rows[:3]
    for row in shown:
        print(f"      {row.file}::{row.name}")
    _render_more_hint(total=len(rows), shown=len(shown))


def _render_crap_actions(rows: list[CrapRow], *, verbose: bool) -> None:
    print("    Cover or simplify hot functions; start with:")
    shown = rows if verbose else rows[:3]
    for row in shown:
        print(f"      {row.path}::{row.name}  cov {row.coverage * 100:.0f}%")
    _render_more_hint(total=len(rows), shown=len(shown))


def _render_more_hint(*, total: int, shown: int) -> None:
    if total > shown:
        print(f"      … {total - shown} more (use --verbose)")


def _render_stages(report: TrustReport) -> None:
    parts: list[str] = []
    if report.coverage_pct is not None:
        parts.append(f"coverage {report.coverage_pct:.0f}%")
    if report.mutation is not None:
        parts.append(f"mutation {report.mutation.score:.0f}%")
    parts.append(f"CRAP {len(report.crap_rows)} over ceiling")
    parts.append(f"suspicious {len(report.suspicious)}")
    ui.section("Signals")
    print("  " + "   ".join(parts))
    print("  run `harness trust --verbose` for full breakdown")


def _delta_arrow(delta: float) -> str:
    if delta > 0:
        return "↑"
    if delta < 0:
        return "↓"
    return "="


def _crap_color(crap: float, crap_max: float) -> str:
    if crap > crap_max + CRAP_RED_MARGIN:
        return RED
    if crap >= crap_max:
        return YELLOW
    return GREEN


# ─────────────── entry point ────────────────────────────────────


def cmd_trust() -> None:
    """Print an actionable trust report; --refresh runs coverage first."""
    start = time.monotonic()
    cfg = load_config()
    ui.command_banner("trust", cfg)
    no_trend = "--no-trend" in sys.argv

    if "--refresh" in sys.argv:
        cmd_coverage(min_pct=0)

    if not Path(".coverage").exists():
        warn_skip("trust: no coverage data — run `harness coverage` first")
        ui.command_footer(start)
        return
    cov_file = generate_coverage_xml()
    if not cov_file.exists():
        warn_skip("trust: coverage.xml not generated — run `harness coverage` first")
        ui.command_footer(start)
        return

    cov_map = parse_coverage(cov_file)
    cov_pct = _coverage_pct(cov_map)

    fns = lizard_functions(cfg.src_dir_arg)
    crap_rows = compute_crap_rows(fns, cov_map, max_crap=cfg.crap_max)
    crap_rows.sort(key=lambda r: r.crap, reverse=True)

    mutation = read_mutation_summary()
    suspicious = _flag_suspicious(_collect_test_inspections(cfg.test_dir, cfg))
    diff_changed = changed_py_files_vs("HEAD~1")

    score = _compute_trust(
        crap_rows=crap_rows,
        mutation=mutation,
        coverage_pct=cov_pct,
        suspicious_count=len(suspicious),
        cfg=cfg,
    )
    cache = _cache_path(cfg.project_root)
    prev_score = None if no_trend else _read_prev_trust(cache)

    report = TrustReport(
        score=score,
        prev_score=prev_score,
        crap_rows=crap_rows,
        suspicious=suspicious,
        mutation=mutation,
        coverage_pct=cov_pct,
        crap_max=cfg.crap_max,
        diff_changed=diff_changed,
        diff_new_crap=[r for r in crap_rows if r.path in diff_changed],
    )
    _render(report, verbose=VERBOSE)

    if not no_trend:
        _write_trust(cache, score)
    ui.command_footer(start)


def _coverage_pct(cov_map: dict[str, dict[int, int]]) -> float | None:
    """Line hit rate (%) across every tracked file, or None when nothing tracked."""
    total = 0
    hit = 0
    for lines in cov_map.values():
        total += len(lines)
        hit += sum(1 for h in lines.values() if h > 0)
    return (hit / total * 100) if total else None


def _verdict_sentence(
    *, suspicious_count: int, crap_count: int, mutation: MutationSummary | None
) -> str:
    bits: list[str] = []
    if suspicious_count:
        bits.append(f"{suspicious_count} suspicious test(s)")
    if crap_count:
        bits.append(f"{crap_count} hot fn(s)")
    if mutation is not None and mutation.survived:
        bits.append(f"{mutation.survived} surviving mutant(s)")
    return ", ".join(bits) if bits else "all clear"
