"""Mutation testing via mutmut. Advisory."""

from __future__ import annotations

import subprocess
import sys
import xml.etree.ElementTree as ET

from harness.git import changed_py_files_vs_main
from harness.runner import GREEN, RED, RESET, arg_value, generate_coverage_xml, python_m, warn_skip

_MUTMUT = python_m("mutmut")


def _coverage_line_rate() -> float | None:
    """Overall coverage.xml line-rate (0..1), or None if unreadable."""
    cov_file = generate_coverage_xml()
    if not cov_file.exists():
        return None
    try:
        root = ET.parse(cov_file).getroot()
    except ET.ParseError:
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
    """Mutant keys look like `harness.foo.bar__mutmut_1`; match vs `harness/foo.py`."""
    module = mutant_key.split("__mutmut_", 1)[0]
    rel = module.replace(".", "/") + ".py"
    return any(c == rel or c.endswith("/" + rel) for c in changed)


def _run_mutmut(timeout: int) -> bool:
    """Run `mutmut run`, SIGTERM after `timeout`. Return True if it completed on its own."""
    with subprocess.Popen([*_MUTMUT, "run"]) as proc:
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
    """Mutation score on `harness/`. Advisory unless --min-score is set."""
    min_cov = float(arg_value("--min-coverage=", "70"))
    rate = _coverage_line_rate()
    if rate is None or rate * 100 < min_cov:
        warn_skip(f"mutation: suite coverage < {min_cov}% — run `harness coverage` first")
        return

    timeout = int(arg_value("--max-runtime=", "600"))
    min_score_arg = arg_value("--min-score=", "")
    min_score = float(min_score_arg) if min_score_arg else None
    changed = changed_py_files_vs_main() if "--changed-only" in sys.argv else None

    completed = _run_mutmut(timeout)

    res = subprocess.run(
        [*_MUTMUT, "results", "--all=true"],
        capture_output=True,
        text=True,
        check=False,
    )
    by_status = _parse_results(res.stdout)

    killed = len(by_status.get("killed", []))
    survived = by_status.get("survived", [])
    total = killed + len(survived) + len(by_status.get("timeout", []))
    score = (killed / total * 100) if total else 0.0

    failed = min_score is not None and score < min_score
    sigil = f"{RED}✗{RESET}" if failed else f"{GREEN}✓{RESET}"
    detail = f"below threshold {min_score:.1f}%" if failed else f"(killed {killed}/{total})"
    partial = "" if completed else " (partial — timeout)"
    print(f"  {sigil} Mutation: score {score:.1f}% {detail}{partial}")
    _print_survivors(survived, changed)
    if failed:
        sys.exit(1)
