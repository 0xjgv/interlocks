"""Mutation testing via mutmut."""

from __future__ import annotations

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from harness.config import load_config
from harness.git import changed_py_files_vs_main
from harness.runner import (
    arg_value,
    capture,
    fail,
    generate_coverage_xml,
    ok,
    python_m,
    warn_skip,
)


def _coverage_line_rate() -> float | None:
    """Overall coverage.xml line-rate (0..1), or None if unreadable."""
    if not Path(".coverage").exists():
        return None
    cov_file = generate_coverage_xml()
    try:
        root = ET.parse(cov_file).getroot()
    except (ET.ParseError, FileNotFoundError):
        return None
    rate = root.get("line-rate")
    return float(rate) if rate is not None else None


def _parse_results(stdout: str) -> dict[str, list[str]]:
    """Group mutant keys by status from `mutmut results --all=true` output."""
    by_status: dict[str, list[str]] = {}
    for line in stdout.splitlines():
        key, sep, status = line.strip().partition(": ")
        if not sep or "__mutmut_" not in key:
            continue
        by_status.setdefault(status, []).append(key)
    return by_status


def _mutant_in_changed(mutant_key: str, changed: set[str]) -> bool:
    """Mutant keys look like `harness.foo.x_bar__mutmut_1`; match vs `harness/foo.py`.

    The trailing dot-component is the mutmut-mangled function name (``x_<name>``),
    which isn't part of the module file path — strip it before resolving.
    """
    head = mutant_key.split("__mutmut_", 1)[0]
    module = head.rsplit(".", 1)[0]
    rel = module.replace(".", "/") + ".py"
    return any(c == rel or c.endswith("/" + rel) for c in changed)


def _run_mutmut(mutmut: list[str], timeout: int) -> bool:
    """Run `mutmut run`, SIGTERM after `timeout`. Return True if it completed on its own."""
    with subprocess.Popen([*mutmut, "run"]) as proc:
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            return False
        return True


def _print_survivors(survived: list[str], changed: set[str] | None) -> None:
    shown = [s for s in survived if changed is None or _mutant_in_changed(s, changed)][:20]
    if not shown:
        return
    print(f"    surviving mutants ({len(shown)} shown):")
    for key in shown:
        print(f"      {key}")


def cmd_mutation() -> None:
    """Mutation score via mutmut (reads ``[tool.mutmut]``).

    CLI flags ``--min-coverage=`` / ``--max-runtime=`` / ``--min-score=`` win;
    otherwise thresholds come from ``cfg.mutation_min_coverage`` /
    ``cfg.mutation_max_runtime`` / ``cfg.mutation_min_score`` (defaults
    70.0 / 600 / 80.0, overridable via ``[tool.harness]``). Advisory by default;
    set ``enforce_mutation = true`` to exit 1 when score < ``mutation_min_score``.
    """
    cfg = load_config()
    min_cov = float(arg_value("--min-coverage=", str(cfg.mutation_min_coverage)))
    rate = _coverage_line_rate()
    if rate is None:
        warn_skip("mutation: no coverage data — run `harness coverage` first")
        return
    pct = rate * 100
    if pct < min_cov:
        warn_skip(f"mutation: suite coverage {pct:.1f}% < {min_cov}%")
        return

    timeout = int(arg_value("--max-runtime=", str(cfg.mutation_max_runtime)))
    min_score_arg = arg_value("--min-score=", "")
    if min_score_arg:
        min_score: float | None = float(min_score_arg)
    elif cfg.enforce_mutation:
        min_score = cfg.mutation_min_score
    else:
        min_score = None
    changed = changed_py_files_vs_main() if "--changed-only" in sys.argv else None

    mutmut = python_m("mutmut")
    completed = _run_mutmut(mutmut, timeout)

    res = capture([*mutmut, "results", "--all=true"])
    by_status = _parse_results(res.stdout)

    killed = len(by_status.get("killed", []))
    survived = by_status.get("survived", [])
    total = killed + len(survived) + len(by_status.get("timeout", []))
    score = (killed / total * 100) if total else 0.0

    failed = min_score is not None and score < min_score
    partial = "" if completed else " (partial — timeout)"
    if failed:
        fail(f"Mutation: score {score:.1f}% below threshold {min_score:.1f}%{partial}")
    else:
        ok(f"Mutation: score {score:.1f}% (killed {killed}/{total}){partial}")
    _print_survivors(survived, changed)
    if failed:
        sys.exit(1)
