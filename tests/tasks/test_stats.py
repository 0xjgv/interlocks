"""Unit tests for harness.tasks.stats — trust report + suspicious-test heuristic."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import harness
from harness.config import HarnessConfig
from harness.metrics import CrapRow, MutationSummary
from harness.tasks import stats as stats_mod
from harness.tasks.stats import (
    TestInspection,
    _collect_test_inspections,
    _compute_trust,
    _emoji,
    _flag_suspicious,
    _read_prev_trust,
    _write_trust,
    cmd_trust,
)

_HARNESS_PKG_ROOT = str(Path(harness.__file__).resolve().parent.parent)


def _cfg(root: Path, **over: object) -> HarnessConfig:
    """Build a HarnessConfig with trust-relevant overrides."""
    return HarnessConfig(
        project_root=root,
        src_dir=root,
        test_dir=root,
        test_runner="pytest",
        test_invoker="python",
        **over,  # pyright: ignore[reportArgumentType]
    )


# ─────────────── _compute_trust ─────────────────────────────────


def _row(crap: float) -> CrapRow:
    return CrapRow(path="a.py", name="f", start=1, end=10, ccn=10, loc=10, coverage=0.5, crap=crap)


def test_compute_trust_perfect_signals() -> None:
    score = _compute_trust(
        crap_rows=[],
        mutation=MutationSummary(killed=10, survived=0, timeout=0, score=100.0),
        coverage_pct=100.0,
        suspicious_count=0,
        cfg=_cfg(Path()),
    )
    assert score == 100.0


def test_compute_trust_missing_mutation_and_coverage() -> None:
    """None signals → no penalty for that slot."""
    score = _compute_trust(
        crap_rows=[],
        mutation=None,
        coverage_pct=None,
        suspicious_count=0,
        cfg=_cfg(Path()),
    )
    assert score == 100.0


def test_compute_trust_crap_overrun_capped() -> None:
    """Big CRAP overrun → penalty capped at CRAP_MAX_PENALTY (30)."""
    cfg = _cfg(Path(), crap_max=30.0)
    score = _compute_trust(
        crap_rows=[_row(1000.0)],
        mutation=None,
        coverage_pct=None,
        suspicious_count=0,
        cfg=cfg,
    )
    assert score == 70.0  # 100 - 30 (capped)


def test_compute_trust_mutation_shortfall() -> None:
    cfg = _cfg(Path(), mutation_min_score=80.0)
    score = _compute_trust(
        crap_rows=[],
        mutation=MutationSummary(killed=0, survived=0, timeout=0, score=70.0),
        coverage_pct=None,
        suspicious_count=0,
        cfg=cfg,
    )
    assert score == 90.0  # 80 - 70 = 10 shortfall


def test_compute_trust_coverage_shortfall() -> None:
    cfg = _cfg(Path(), coverage_min=80)
    score = _compute_trust(
        crap_rows=[],
        mutation=None,
        coverage_pct=60.0,
        suspicious_count=0,
        cfg=cfg,
    )
    assert score == 80.0  # 80 - 60 = 20


def test_compute_trust_suspicious_penalty() -> None:
    score = _compute_trust(
        crap_rows=[],
        mutation=None,
        coverage_pct=None,
        suspicious_count=4,
        cfg=_cfg(Path()),
    )
    assert score == 88.0  # 100 - 4*3


def test_compute_trust_floors_at_zero() -> None:
    cfg = _cfg(Path(), crap_max=30.0, mutation_min_score=100.0, coverage_min=100)
    score = _compute_trust(
        crap_rows=[_row(1000.0)],
        mutation=MutationSummary(killed=0, survived=0, timeout=0, score=0.0),
        coverage_pct=0.0,
        suspicious_count=50,
        cfg=cfg,
    )
    assert score == 0.0


def test_emoji_thresholds() -> None:
    assert _emoji(100.0) == "🟢"
    assert _emoji(85.0) == "🟢"
    assert _emoji(84.9) == "🟡"
    assert _emoji(65.0) == "🟡"
    assert _emoji(64.9) == "🔴"
    assert _emoji(0.0) == "🔴"


# ─────────────── AST walker + _flag_suspicious ──────────────────

_TEST_FILE_SRC = textwrap.dedent(
    """\
    import unittest

    def test_no_asserts():
        x = 1
        y = 2
        z = x + y
        print(z)
        log = "ran"
        return log

    def test_good():
        x = 1
        y = 2
        assert x + y == 3

    def test_all_trivial():
        a = 1
        b = 2
        c = 3
        d = 4
        assert True
        assert 1

    def test_short_no_assert():
        x = 1

    class TestFoo(unittest.TestCase):
        def test_method_no_asserts(self):
            x = 1
            y = 2
            z = x + y
            w = z * 2
            v = w - 1
            return v

        def test_method_good(self):
            self.assertEqual(1, 1)

    def not_a_test():
        assert False
    """
)


@pytest.fixture
def test_dir(tmp_path: Path) -> Path:
    (tmp_path / "test_foo.py").write_text(_TEST_FILE_SRC, encoding="utf-8")
    return tmp_path


def test_collect_inspections_finds_functions_and_methods(test_dir: Path) -> None:
    rows = _collect_test_inspections(test_dir)
    names = {r.name for r in rows}
    assert "test_no_asserts" in names
    assert "test_good" in names
    assert "TestFoo.test_method_no_asserts" in names
    assert "TestFoo.test_method_good" in names
    assert "not_a_test" not in names


def test_collect_inspections_missing_dir_returns_empty(tmp_path: Path) -> None:
    assert _collect_test_inspections(tmp_path / "nope") == []


def test_flag_suspicious_no_asserts(test_dir: Path) -> None:
    rows = _collect_test_inspections(test_dir)
    flagged = {r.name for r in _flag_suspicious(rows)}
    assert "test_no_asserts" in flagged


def test_flag_suspicious_all_trivial(test_dir: Path) -> None:
    rows = _collect_test_inspections(test_dir)
    flagged = {r.name for r in _flag_suspicious(rows)}
    assert "test_all_trivial" in flagged


def test_flag_suspicious_exempts_good(test_dir: Path) -> None:
    rows = _collect_test_inspections(test_dir)
    flagged = {r.name for r in _flag_suspicious(rows)}
    assert "test_good" not in flagged
    assert "TestFoo.test_method_good" not in flagged


def test_flag_suspicious_respects_loc_floor(test_dir: Path) -> None:
    """Tests ≤ SUSPICIOUS_MIN_LOC lines are exempt even with zero asserts."""
    rows = _collect_test_inspections(test_dir)
    flagged = {r.name for r in _flag_suspicious(rows)}
    assert "test_short_no_assert" not in flagged


def test_flag_suspicious_methods_caught(test_dir: Path) -> None:
    rows = _collect_test_inspections(test_dir)
    flagged = {r.name for r in _flag_suspicious(rows)}
    assert "TestFoo.test_method_no_asserts" in flagged


# ─────────────── trust.json cache ──────────────────────────────


def test_read_prev_trust_missing_file_returns_none(tmp_path: Path) -> None:
    assert _read_prev_trust(tmp_path / "nope.json") is None


def test_read_prev_trust_corrupt_json_returns_none(tmp_path: Path) -> None:
    cache = tmp_path / "trust.json"
    cache.write_text("not json", encoding="utf-8")
    assert _read_prev_trust(cache) is None


def test_read_prev_trust_empty_history(tmp_path: Path) -> None:
    cache = tmp_path / "trust.json"
    cache.write_text(json.dumps({"history": []}), encoding="utf-8")
    assert _read_prev_trust(cache) is None


def test_write_and_read_trust_round_trip(tmp_path: Path) -> None:
    cache = tmp_path / "trust.json"
    _write_trust(cache, 73.5)
    assert _read_prev_trust(cache) == 73.5


def test_write_trust_appends_history(tmp_path: Path) -> None:
    cache = tmp_path / "trust.json"
    _write_trust(cache, 70.0)
    _write_trust(cache, 80.0)
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert len(data["history"]) == 2
    assert data["history"][-1]["score"] == 80.0


def test_write_trust_caps_history_at_twenty(tmp_path: Path) -> None:
    cache = tmp_path / "trust.json"
    for i in range(25):
        _write_trust(cache, float(i))
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert len(data["history"]) == 20
    assert data["history"][-1]["score"] == 24.0
    assert data["history"][0]["score"] == 5.0


# ─────────────── cmd_trust end-to-end ──────────────────────────

_MODULE_SRC = textwrap.dedent(
    """\
    def inc(x):
        return x + 1
    """
)

_COV_TEST_SRC = textwrap.dedent(
    """\
    import unittest
    from mypkg.mod import inc

    class TestInc(unittest.TestCase):
        def test_inc(self):
            self.assertEqual(inc(1), 2)
    """
)

_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "stats-probe"
    version = "0.0.1"
    requires-python = ">=3.13"

    [tool.coverage.run]
    source = ["mypkg"]
    branch = true
    """
)


@pytest.fixture
def tmp_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Small project with source + covering test; primes ``.coverage`` + ``coverage.xml``."""
    (tmp_path / "pyproject.toml").write_text(
        _PYPROJECT + '\n[tool.harness]\nsrc_dir = "mypkg"\ntest_dir = "tests"\n',
        encoding="utf-8",
    )
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(_MODULE_SRC, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "test_mod.py").write_text(_COV_TEST_SRC, encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
        ],
        cwd=tmp_path,
        check=True,
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    return tmp_path


def test_cmd_trust_skips_without_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    from harness.config import clear_cache

    clear_cache()
    monkeypatch.setattr(sys, "argv", ["harness", "trust"])
    cmd_trust()
    captured = capsys.readouterr()
    assert "no coverage" in captured.out.lower()


def test_cmd_trust_prints_report(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["harness", "trust", "--no-trend"])
    cmd_trust()
    captured = capsys.readouterr()
    assert "command=trust" in captured.out
    assert "── Trust" in captured.out
    assert "── Suspicious Tests" in captured.out
    assert "── Hot Files" in captured.out
    assert "── Next Actions" in captured.out


def test_cmd_trust_writes_trend_file(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["harness", "trust"])
    cmd_trust()
    cache = tmp_project / ".harness" / "trust.json"
    assert cache.is_file()
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert "history" in data
    assert len(data["history"]) == 1


def test_cmd_trust_no_trend_skips_cache(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["harness", "trust", "--no-trend"])
    cmd_trust()
    assert not (tmp_project / ".harness" / "trust.json").exists()


def test_cmd_trust_second_run_shows_delta(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["harness", "trust"])
    cmd_trust()
    capsys.readouterr()  # drain first run
    cmd_trust()
    captured = capsys.readouterr()
    assert "since last run" in captured.out


def test_cmd_trust_refresh_runs_coverage_first(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[object] = []

    def fake_coverage(*, min_pct: int | None = None) -> None:
        calls.append(("coverage", min_pct))

    monkeypatch.setattr(stats_mod, "cmd_coverage", fake_coverage)
    monkeypatch.setattr(sys, "argv", ["harness", "trust", "--refresh", "--no-trend"])

    cmd_trust()

    captured = capsys.readouterr()
    assert calls == [("coverage", 0)]
    assert "command=trust" in captured.out
    assert "── Trust" in captured.out
    assert "run `harness trust --verbose`" in captured.out


def test_cmd_trust_refresh_failure_stops_before_report(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_coverage(*, min_pct: int | None = None) -> None:
        raise SystemExit(7)

    monkeypatch.setattr(stats_mod, "cmd_coverage", fail_coverage)
    monkeypatch.setattr(sys, "argv", ["harness", "trust", "--refresh", "--no-trend"])

    with pytest.raises(SystemExit) as exc:
        cmd_trust()

    assert exc.value.code == 7
    assert "── Trust" not in capsys.readouterr().out


# ─────────────── CLI wiring smoke ──────────────────────────────


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{_HARNESS_PKG_ROOT}{os.pathsep}{existing}" if existing else _HARNESS_PKG_ROOT
    )
    return env


def test_cli_help_lists_trust() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "harness.cli", "help"],
        capture_output=True,
        text=True,
        check=False,
        env=_subprocess_env(),
    )
    assert result.returncode == 0
    assert "trust" in result.stdout
    assert "Reports:" in result.stdout


def test_verdict_sentence_empty() -> None:
    assert (
        stats_mod._verdict_sentence(suspicious_count=0, crap_count=0, mutation=None) == "all clear"
    )


def test_verdict_sentence_concat() -> None:
    out = stats_mod._verdict_sentence(
        suspicious_count=2,
        crap_count=1,
        mutation=MutationSummary(killed=10, survived=3, timeout=0, score=80.0),
    )
    assert "2 suspicious" in out
    assert "1 hot" in out
    assert "3 surviving" in out


def test_render_does_not_crash_on_empty_report(capsys: pytest.CaptureFixture[str]) -> None:
    from harness.tasks.stats import TrustReport, _render

    report = TrustReport(
        score=100.0,
        prev_score=None,
        crap_rows=[],
        suspicious=[],
        mutation=None,
        coverage_pct=None,
        crap_max=30.0,
    )
    _render(report, verbose=False)
    captured = capsys.readouterr()
    assert "── Trust" in captured.out
    assert "(none)" in captured.out
    assert "── Next Actions" in captured.out


def test_inspection_dataclass_fields() -> None:
    """Sanity: TestInspection fields line up with AST walker outputs."""
    t = TestInspection(file="a.py", name="test_x", loc=3, assert_count=1, trivial_asserts=0)
    assert t.loc == 3
    assert t.name == "test_x"
