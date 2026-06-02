"""Unit tests for interlocks.tasks.stats — trust report + suspicious-test heuristic."""

from __future__ import annotations

import ast
import inspect
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import interlocks
from interlocks.config import InterlockConfig, clear_cache
from interlocks.metrics import CrapRow, MutationSummary
from interlocks.tasks import stats as stats_mod
from interlocks.tasks.stats import (
    TestInspection,
    TrustReport,
    _collect_test_inspections,
    _compute_trust,
    _emoji,
    _flag_suspicious,
    _inspect_tree,
    _read_prev_trust,
    _render,
    _write_trust,
    cmd_trust,
)

_INTERLOCK_PKG_ROOT = str(Path(interlocks.__file__).resolve().parent.parent)


def _cfg(root: Path, **over: object) -> InterlockConfig:
    """Build a InterlockConfig with trust-relevant overrides."""
    return InterlockConfig(
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


def _with_node(source: str) -> ast.With:
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.With)
    return node


def test_compute_trust_perfect_signals() -> None:
    score = _compute_trust(
        crap_rows=[],
        mutation=MutationSummary(killed=10, survived=0, timeout=0, score=100.0),
        coverage_pct=100.0,
        suspicious_count=0,
        cfg=_cfg(Path()),
    )
    assert score == 100.0


def test_compute_trust_missing_optional_signals() -> None:
    """Missing optional signals do not penalize trust."""
    score = _compute_trust(
        crap_rows=[],
        mutation=None,
        coverage_pct=None,
        suspicious_count=0,
        cfg=_cfg(Path(), coverage_min=0, mutation_min_score=0.0),
    )
    assert score == 100.0


def test_compute_trust_missing_configured_mutation_penalizes() -> None:
    cfg = _cfg(Path(), mutation_min_score=80.0)
    score = _compute_trust(
        crap_rows=[],
        mutation=None,
        coverage_pct=None,
        suspicious_count=0,
        cfg=cfg,
    )
    assert score == 70.0


def test_compute_trust_crap_overrun_capped() -> None:
    """Big CRAP overrun → penalty capped at CRAP_MAX_PENALTY (30)."""
    cfg = _cfg(Path(), crap_max=30.0, mutation_min_score=0.0)
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


def test_compute_trust_partial_mutation_penalizes_even_above_floor() -> None:
    cfg = _cfg(Path(), mutation_min_score=60.0)
    score = _compute_trust(
        crap_rows=[],
        mutation=MutationSummary(killed=9, survived=1, timeout=0, score=90.0, completed=False),
        coverage_pct=None,
        suspicious_count=0,
        cfg=cfg,
    )
    assert score == 70.0


def test_compute_trust_coverage_shortfall() -> None:
    cfg = _cfg(Path(), coverage_min=80, mutation_min_score=0.0)
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
        cfg=_cfg(Path(), mutation_min_score=0.0),
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


def test_inspect_counts_pytest_raises_as_assertion() -> None:
    src = textwrap.dedent("""\
        import pytest
        def test_x():
            with pytest.raises(ValueError, match="bad"):
                do_thing()
    """)
    tree = ast.parse(src)
    [insp] = _inspect_tree(tree, "test_x.py")
    assert insp.assert_count == 1
    assert insp.trivial_asserts == 0


def test_inspect_counts_pytest_warns_and_deprecated_call() -> None:
    src = textwrap.dedent("""\
        import pytest
        def test_x():
            with pytest.warns(DeprecationWarning):
                f()
            with pytest.deprecated_call():
                g()
    """)
    tree = ast.parse(src)
    [insp] = _inspect_tree(tree, "test_x.py")
    assert insp.assert_count == 2


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
    requires-python = ">=3.11"

    [tool.coverage.run]
    source = ["mypkg"]
    branch = true

    [tool.interlocks]
    src_dir = "mypkg"
    test_dir = "tests"
    """
)


@pytest.fixture
def tmp_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Small project with source + covering test; primes ``.coverage`` + ``coverage.xml``."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(_MODULE_SRC, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "test_mod.py").write_text(_COV_TEST_SRC, encoding="utf-8")
    subprocess.run(
        [sys.executable, "-m", "coverage", "run", "-m", "unittest", "discover", "-s", "tests"],
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
    clear_cache()
    monkeypatch.setattr(sys, "argv", ["interlocks", "trust"])
    cmd_trust()
    captured = capsys.readouterr()
    assert "no coverage" in captured.out.lower()


def test_cmd_trust_prints_report(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "trust", "--no-trend"])
    cmd_trust()
    captured = capsys.readouterr()
    assert "command=trust" in captured.out
    assert "── Trust" in captured.out
    assert "── Suspicious Tests" in captured.out
    assert "── Hot Files" in captured.out
    assert "── Next Actions" in captured.out


def test_trust_json_is_parseable(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "trust", "--json", "--no-trend"])
    cmd_trust()
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "trust"
    assert set(payload["score"]) == {"earned", "max"}
    assert payload["verdict"] in {"HEALTHY", "CAUTION", "RISKY"}
    assert "coverage_pct" in payload
    assert isinstance(payload["next_actions"], list)
    assert isinstance(payload["crap_offenders"], list)
    assert isinstance(payload["suspicious_tests"], list)


def test_trust_json_error_when_no_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    clear_cache()
    monkeypatch.setattr(sys, "argv", ["interlocks", "trust", "--json"])
    cmd_trust()
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "trust"
    assert "error" in payload
    assert payload["next_actions"] == [
        {
            "kind": "coverage",
            "message": "no coverage data — run `interlocks gate coverage` first",
        }
    ]


def test_trust_json_error_when_property_coverage_is_stale(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    properties = tmp_project / "properties"
    properties.mkdir()
    prop = properties / "test_mod_properties.py"
    prop.write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")
    cov_mtime = (tmp_project / ".coverage").stat().st_mtime
    os.utime(prop, (cov_mtime + 10, cov_mtime + 10))

    clear_cache()
    monkeypatch.setattr(sys, "argv", ["interlocks", "trust", "--json", "--no-trend"])
    cmd_trust()

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "command": "trust",
        "error": "coverage data is stale — run `interlocks trust --refresh --json --no-trend`",
        "next_actions": [
            {
                "kind": "coverage",
                "message": (
                    "coverage data is stale — run `interlocks trust --refresh --json --no-trend`"
                ),
            }
        ],
    }


def test_cmd_trust_writes_trend_file(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "trust"])
    cmd_trust()
    cache = tmp_project / ".interlocks" / "trust.json"
    assert cache.is_file()
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert "history" in data
    assert len(data["history"]) == 1


def test_cmd_trust_no_trend_skips_cache(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "trust", "--no-trend"])
    cmd_trust()
    assert not (tmp_project / ".interlocks" / "trust.json").exists()


def test_cmd_trust_second_run_shows_delta(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "trust"])
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

    def fake_coverage(
        *,
        min_pct: int | None = None,
        include_properties: bool = False,
        property_profile: str = "ci",
        emit_json: bool = True,
    ) -> None:
        calls.append(("coverage", min_pct, include_properties, property_profile, emit_json))

    monkeypatch.setattr(stats_mod, "cmd_coverage", fake_coverage)
    monkeypatch.setattr(sys, "argv", ["interlocks", "trust", "--refresh", "--no-trend"])

    cmd_trust()

    captured = capsys.readouterr()
    assert calls == [("coverage", 0, True, "ci", False)]
    assert "command=trust" in captured.out
    assert "── Trust" in captured.out
    assert "run `interlocks trust --verbose`" in captured.out


def test_cmd_trust_refresh_json_is_parseable_after_refresh(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[object] = []

    def fake_coverage(
        *,
        min_pct: int | None = None,
        include_properties: bool = False,
        property_profile: str = "ci",
        emit_json: bool = True,
    ) -> None:
        calls.append(("coverage", min_pct, include_properties, property_profile, emit_json))

    monkeypatch.setattr(stats_mod, "cmd_coverage", fake_coverage)
    monkeypatch.setattr(sys, "argv", ["interlocks", "trust", "--refresh", "--json", "--no-trend"])

    cmd_trust()

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert calls == [("coverage", 0, True, "ci", False)]
    assert payload["command"] == "trust"


def test_cmd_trust_refresh_failure_stops_before_report(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_coverage(**_kwargs: object) -> None:
        raise SystemExit(7)

    monkeypatch.setattr(stats_mod, "cmd_coverage", fail_coverage)
    monkeypatch.setattr(sys, "argv", ["interlocks", "trust", "--refresh", "--no-trend"])

    with pytest.raises(SystemExit) as exc:
        cmd_trust()

    assert exc.value.code == 7
    assert "── Trust" not in capsys.readouterr().out


def test_cmd_trust_refresh_failure_json_reports_error(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_coverage(**_kwargs: object) -> None:
        raise SystemExit(7)

    monkeypatch.setattr(stats_mod, "cmd_coverage", fail_coverage)
    monkeypatch.setattr(sys, "argv", ["interlocks", "trust", "--refresh", "--json", "--no-trend"])

    with pytest.raises(SystemExit) as exc:
        cmd_trust()

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exc.value.code == 7
    assert payload == {
        "command": "trust",
        "error": "coverage refresh failed",
        "exit_code": 7,
        "next_actions": [
            {
                "kind": "coverage",
                "message": "Run `interlocks gate coverage --properties=ci` for details.",
            }
        ],
    }


# ─────────────── CLI wiring smoke ──────────────────────────────


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{_INTERLOCK_PKG_ROOT}{os.pathsep}{existing}" if existing else _INTERLOCK_PKG_ROOT
    )
    return env


def test_cli_help_lists_trust() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "help", "--advanced"],
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
        stats_mod._verdict_sentence(
            stats_mod._VerdictSignals(suspicious_count=0, crap_count=0, mutation=None)
        )
        == "all clear"
    )


def test_verdict_sentence_missing_expected_mutation() -> None:
    assert (
        stats_mod._verdict_sentence(
            stats_mod._VerdictSignals(
                suspicious_count=0,
                crap_count=0,
                mutation=None,
                mutation_min_score=60.0,
            )
        )
        == "mutation unavailable"
    )


def test_verdict_sentence_concat() -> None:
    out = stats_mod._verdict_sentence(
        stats_mod._VerdictSignals(
            suspicious_count=2,
            crap_count=1,
            mutation=MutationSummary(killed=10, survived=3, timeout=0, score=80.0),
            mutation_min_score=90.0,
            coverage_pct=70.0,
            coverage_min=80.0,
        )
    )
    assert "2 suspicious" in out
    assert "1 hot" in out
    assert "coverage 70% below 80%" in out
    assert "mutation 80% below 90%" in out


def test_verdict_sentence_ignores_nonactionable_mutation_survivors() -> None:
    assert (
        stats_mod._verdict_sentence(
            stats_mod._VerdictSignals(
                suspicious_count=0,
                crap_count=0,
                mutation=MutationSummary(killed=10, survived=3, timeout=0, score=80.0),
                mutation_min_score=0.0,
                coverage_pct=90.0,
                coverage_min=80.0,
            )
        )
        == "all clear"
    )


def test_crap_color_threshold_boundaries_are_exact() -> None:
    assert stats_mod._crap_color(29.99, 30.0) == stats_mod.GREEN
    assert stats_mod._crap_color(30.0, 30.0) == stats_mod.YELLOW
    assert stats_mod._crap_color(35.0, 30.0) == stats_mod.YELLOW
    assert stats_mod._crap_color(35.01, 30.0) == stats_mod.RED


def test_verdict_sentence_marks_partial_mutation_shortfall() -> None:
    assert (
        stats_mod._verdict_sentence(
            stats_mod._VerdictSignals(
                suspicious_count=0,
                crap_count=0,
                mutation=MutationSummary(
                    killed=57,
                    survived=43,
                    timeout=0,
                    score=57.0,
                    completed=False,
                ),
                mutation_min_score=60.0,
            )
        )
        == "partial mutation 57% below 60%"
    )


def test_verdict_sentence_marks_partial_mutation_above_floor() -> None:
    assert (
        stats_mod._verdict_sentence(
            stats_mod._VerdictSignals(
                suspicious_count=0,
                crap_count=0,
                mutation=MutationSummary(
                    killed=9,
                    survived=1,
                    timeout=0,
                    score=90.0,
                    completed=False,
                ),
                mutation_min_score=60.0,
            )
        )
        == "partial mutation evidence"
    )


def test_trust_next_actions_explain_mutation_and_coverage_shortfalls() -> None:
    report = TrustReport(
        score=70.0,
        prev_score=None,
        crap_rows=[],
        suspicious=[],
        mutation=MutationSummary(
            killed=1,
            survived=2,
            timeout=0,
            score=50.0,
            survivors=["pkg.mod.fn__mutmut_1", "pkg.mod.fn__mutmut_2"],
        ),
        coverage_pct=70.0,
        crap_max=30.0,
        coverage_min=80.0,
        mutation_min_score=90.0,
    )

    actions = {action["kind"]: action for action in stats_mod._trust_next_actions(report)}

    assert actions["mutation"]["targets"] == ["pkg.mod.fn__mutmut_1", "pkg.mod.fn__mutmut_2"]
    mutation_message = actions["mutation"]["message"]
    coverage_message = actions["coverage"]["message"]
    assert isinstance(mutation_message, str)
    assert isinstance(coverage_message, str)
    assert "interlocks gate mutation --min-score=90" in mutation_message
    assert actions["coverage"]["targets"] == []
    assert "80%" in coverage_message
    assert "refresh" not in actions


def test_trust_mutation_action_reports_completed_survivor_targets() -> None:
    survivors = [f"pkg.mod.fn__mutmut_{index}" for index in range(25)]
    report = TrustReport(
        score=70.0,
        prev_score=None,
        crap_rows=[],
        suspicious=[],
        mutation=MutationSummary(
            killed=1,
            survived=len(survivors),
            timeout=0,
            score=50.0,
            survivors=survivors,
            completed=True,
        ),
        coverage_pct=90.0,
        crap_max=30.0,
        coverage_min=80.0,
        mutation_min_score=90.0,
        mutation_max_runtime=900,
    )

    assert stats_mod._trust_mutation_action(report) == {
        "kind": "mutation",
        "message": "Run `interlocks gate mutation --min-score=90 --max-runtime=900`; cover or "
        "simplify surviving mutants, or lower mutation_min_score after review.",
        "targets": survivors[: stats_mod.TRUST_ACTION_TARGET_LIMIT],
        "omitted_targets": 5,
    }


def test_trust_mutation_action_reports_incomplete_without_targets() -> None:
    report = TrustReport(
        score=70.0,
        prev_score=None,
        crap_rows=[],
        suspicious=[],
        mutation=MutationSummary(
            killed=9,
            survived=1,
            timeout=0,
            score=90.0,
            survivors=["pkg.mod.fn__mutmut_1"],
            completed=False,
        ),
        coverage_pct=90.0,
        crap_max=30.0,
        coverage_min=80.0,
        mutation_min_score=60.0,
        mutation_max_runtime=900,
    )

    assert stats_mod._trust_mutation_action(report) == {
        "kind": "mutation",
        "message": "Last mutation run timed out; rerun `interlocks gate mutation --min-score=60 "
        "--max-runtime=900` with more runtime, then cover or simplify surviving mutants.",
    }


def test_trust_next_actions_caps_noisy_mutation_targets() -> None:
    survivors = [f"pkg.mod.fn__mutmut_{index}" for index in range(30)]
    report = TrustReport(
        score=70.0,
        prev_score=None,
        crap_rows=[],
        suspicious=[],
        mutation=MutationSummary(
            killed=1,
            survived=len(survivors),
            timeout=0,
            score=50.0,
            survivors=survivors,
        ),
        coverage_pct=90.0,
        crap_max=30.0,
        coverage_min=80.0,
        mutation_min_score=90.0,
    )

    actions = {action["kind"]: action for action in stats_mod._trust_next_actions(report)}

    assert actions["mutation"]["targets"] == survivors[: stats_mod.TRUST_ACTION_TARGET_LIMIT]
    assert actions["mutation"]["omitted_targets"] == 10


def test_trust_json_score_display_is_conservative_with_actions() -> None:
    report = TrustReport(
        score=99.9,
        prev_score=None,
        crap_rows=[],
        suspicious=[],
        mutation=MutationSummary(
            killed=999,
            survived=1,
            timeout=0,
            score=59.9,
            survivors=["pkg.mod.fn__mutmut_1"],
        ),
        coverage_pct=94.0,
        crap_max=30.0,
        mutation_min_score=60.0,
        mutation_max_runtime=900,
    )

    payload = stats_mod._trust_json(report)

    assert payload["score"] == {"earned": 99, "max": 100}
    assert payload["next_actions"]


def test_trust_next_action_explains_partial_mutation_timeout() -> None:
    report = TrustReport(
        score=97.0,
        prev_score=None,
        crap_rows=[],
        suspicious=[],
        mutation=MutationSummary(
            killed=57,
            survived=43,
            timeout=0,
            score=57.0,
            survivors=["pkg.mod.fn__mutmut_1"],
            completed=False,
        ),
        coverage_pct=94.0,
        crap_max=30.0,
        mutation_min_score=60.0,
        mutation_max_runtime=900,
    )

    actions = {action["kind"]: action for action in stats_mod._trust_next_actions(report)}

    message = actions["mutation"]["message"]
    assert isinstance(message, str)
    assert "timed out" in message
    assert "with more runtime" in message
    assert "interlocks gate mutation --min-score=60 --max-runtime=900" in message
    assert "targets" not in actions["mutation"]
    assert "omitted_targets" not in actions["mutation"]


def test_trust_next_action_explains_partial_mutation_even_above_floor() -> None:
    report = TrustReport(
        score=70.0,
        prev_score=None,
        crap_rows=[],
        suspicious=[],
        mutation=MutationSummary(
            killed=9,
            survived=1,
            timeout=0,
            score=90.0,
            survivors=["pkg.mod.fn__mutmut_1"],
            completed=False,
        ),
        coverage_pct=94.0,
        crap_max=30.0,
        mutation_min_score=60.0,
        mutation_max_runtime=900,
    )

    actions = {action["kind"]: action for action in stats_mod._trust_next_actions(report)}

    message = actions["mutation"]["message"]
    assert isinstance(message, str)
    assert "timed out" in message
    assert "targets" not in actions["mutation"]


def test_mutation_incomplete_requires_evidence_floor_and_incomplete_run() -> None:
    base = {
        "score": 70.0,
        "prev_score": None,
        "crap_rows": [],
        "suspicious": [],
        "coverage_pct": 90.0,
        "crap_max": 30.0,
        "coverage_min": 80.0,
    }
    partial = MutationSummary(killed=1, survived=1, timeout=0, score=50.0, completed=False)

    assert not stats_mod._mutation_incomplete(
        TrustReport(mutation=None, mutation_min_score=60.0, **base)
    )
    assert not stats_mod._mutation_incomplete(
        TrustReport(mutation=partial, mutation_min_score=0.0, **base)
    )
    assert stats_mod._mutation_incomplete(
        TrustReport(mutation=partial, mutation_min_score=1.0, **base)
    )
    assert not stats_mod._mutation_incomplete(
        TrustReport(
            mutation=MutationSummary(killed=1, survived=0, timeout=0, score=100.0, completed=True),
            mutation_min_score=1.0,
            **base,
        )
    )


def test_render_next_actions_omits_generic_refresh_after_specific_action(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = TrustReport(
        score=99.0,
        prev_score=None,
        crap_rows=[],
        suspicious=[],
        mutation=MutationSummary(
            killed=999,
            survived=1,
            timeout=0,
            score=59.9,
            survivors=["pkg.mod.fn__mutmut_1"],
        ),
        coverage_pct=94.0,
        crap_max=30.0,
        coverage_min=80.0,
        mutation_min_score=60.0,
    )

    stats_mod._render_next_actions(report, verbose=False)

    out = capsys.readouterr().out
    assert "Run `interlocks gate mutation --min-score=60`" in out
    assert "trust --refresh" not in out


def test_print_truncated_uses_default_limit_and_indent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stats_mod._print_truncated(
        list(range(11)),
        verbose=False,
        formatter=lambda value: f"row {value}",
    )

    assert capsys.readouterr().out == (
        "row 0\n"
        "row 1\n"
        "row 2\n"
        "row 3\n"
        "row 4\n"
        "row 5\n"
        "row 6\n"
        "row 7\n"
        "row 8\n"
        "row 9\n"
        "    … 1 more (use --verbose)\n"
    )


def test_print_truncated_default_signature_is_stable() -> None:
    signature = inspect.signature(stats_mod._print_truncated)

    assert signature.parameters["limit"].default == 10
    assert signature.parameters["indent"].default == "    "


def test_has_next_actions_treats_each_signal_independently() -> None:
    base = {
        "score": 100.0,
        "prev_score": None,
        "crap_rows": [],
        "suspicious": [],
        "mutation": None,
        "coverage_pct": 90.0,
        "crap_max": 30.0,
        "coverage_min": 80.0,
        "mutation_min_score": 0.0,
    }
    suspicious = TestInspection(
        file="tests/t.py",
        name="test_light",
        loc=8,
        assert_count=0,
        trivial_asserts=0,
    )
    hot = CrapRow(
        path="pkg/a.py",
        name="hot",
        start=1,
        end=10,
        ccn=8,
        loc=10,
        coverage=0.25,
        crap=40.0,
    )

    assert stats_mod._has_next_actions(TrustReport(**base)) is False
    assert stats_mod._has_next_actions(TrustReport(**{**base, "suspicious": [suspicious]})) is True
    assert stats_mod._has_next_actions(TrustReport(**{**base, "crap_rows": [hot]})) is True
    assert stats_mod._has_next_actions(TrustReport(**{**base, "mutation_min_score": 60.0})) is True
    assert (
        stats_mod._has_next_actions(
            TrustReport(**{
                **base,
                "mutation": MutationSummary(killed=1, survived=1, timeout=0, score=50.0),
                "mutation_min_score": 60.0,
            })
        )
        is True
    )
    assert stats_mod._has_next_actions(TrustReport(**{**base, "coverage_pct": 70.0})) is True


def test_pytest_assert_with_skips_non_call_items_and_requires_pytest_name() -> None:
    assert stats_mod._is_pytest_assert_with(
        _with_node("with lock, pytest.raises(ValueError):\n    pass\n")
    )
    assert not stats_mod._is_pytest_assert_with(
        _with_node("with helper.raises(ValueError):\n    pass\n")
    )
    assert not stats_mod._is_pytest_assert_with(
        _with_node("with get_pytest().raises(ValueError):\n    pass\n")
    )
    assert not stats_mod._is_pytest_assert_with(_with_node("with raises(ValueError):\n    pass\n"))
    assert not stats_mod._is_pytest_assert_with(
        _with_node("with pytest.skip(ValueError):\n    pass\n")
    )


def test_format_suspicious_uses_exact_zero_and_trivial_details() -> None:
    zero = TestInspection(
        file="tests/t.py",
        name="test_zero",
        loc=8,
        assert_count=0,
        trivial_asserts=0,
    )
    trivial = TestInspection(
        file="tests/t.py",
        name="test_trivial",
        loc=9,
        assert_count=2,
        trivial_asserts=2,
    )

    assert stats_mod._format_suspicious(zero) == "    tests/t.py::test_zero  8 LOC, 0 asserts"
    assert (
        stats_mod._format_suspicious(trivial)
        == "    tests/t.py::test_trivial  9 LOC, 2 assert(s) (trivial)"
    )


def test_render_mutation_next_action_preserves_missing_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = TrustReport(
        score=70.0,
        prev_score=None,
        crap_rows=[],
        suspicious=[],
        mutation=None,
        coverage_pct=94.0,
        crap_max=30.0,
        mutation_min_score=60.0,
        mutation_max_runtime=900,
    )

    stats_mod._render_mutation_next_action(report, verbose=False)

    assert (
        capsys.readouterr().out
        == "    Run `interlocks gate mutation --min-score=60 --max-runtime=900`.\n"
    )


def test_render_mutation_next_action_preserves_survivors_under_verbose(
    capsys: pytest.CaptureFixture[str],
) -> None:
    survivors = [f"pkg.mod.x_func__mutmut_{i}" for i in range(4)]
    report = TrustReport(
        score=70.0,
        prev_score=None,
        crap_rows=[],
        suspicious=[],
        mutation=MutationSummary(
            killed=10, survived=4, timeout=0, score=50.0, survivors=survivors
        ),
        coverage_pct=94.0,
        crap_max=30.0,
        mutation_min_score=60.0,
        mutation_max_runtime=900,
    )

    stats_mod._render_mutation_next_action(report, verbose=True)

    out = capsys.readouterr().out
    assert "Run `interlocks gate mutation --min-score=60 --max-runtime=900`" in out
    for survivor in survivors:
        assert f"      {survivor}" in out
    assert "more (use --verbose)" not in out


def test_render_mutation_actions_limits_completed_survivors_when_not_verbose(
    capsys: pytest.CaptureFixture[str],
) -> None:
    survivors = [f"pkg.mod.x_func__mutmut_{i}" for i in range(4)]

    stats_mod._render_mutation_actions(
        MutationSummary(killed=10, survived=4, timeout=0, score=50.0, survivors=survivors),
        60.0,
        900,
        verbose=False,
    )

    assert capsys.readouterr().out == (
        "    Run `interlocks gate mutation --min-score=60 --max-runtime=900`; cover or simplify "
        "surviving mutants, or lower mutation_min_score after review.\n"
        "      pkg.mod.x_func__mutmut_0\n"
        "      pkg.mod.x_func__mutmut_1\n"
        "      pkg.mod.x_func__mutmut_2\n"
        "      … 1 more (use --verbose)\n"
    )


def test_render_mutation_actions_omits_partial_survivor_rows(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stats_mod._render_mutation_actions(
        MutationSummary(
            killed=10,
            survived=4,
            timeout=0,
            score=50.0,
            survivors=["pkg.mod.x_func__mutmut_0"],
            completed=False,
        ),
        60.0,
        900,
        verbose=False,
    )

    assert capsys.readouterr().out == (
        "    Last mutation run timed out; rerun `interlocks gate mutation --min-score=60 "
        "--max-runtime=900` with more runtime, then cover or simplify surviving mutants.\n"
    )


def test_render_suspicious_actions_uses_exact_header_rows_and_limit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rows = [
        TestInspection(
            file="tests/t.py", name=f"test_{i}", loc=10, assert_count=0, trivial_asserts=0
        )
        for i in range(4)
    ]

    stats_mod._render_suspicious_actions(rows, verbose=False)

    assert capsys.readouterr().out == (
        "    Add behavioral assertions, or shorten/mark intentional smoke tests:\n"
        "      tests/t.py::test_0\n"
        "      tests/t.py::test_1\n"
        "      tests/t.py::test_2\n"
        "      … 1 more (use --verbose)\n"
    )


def test_render_crap_actions_uses_exact_header_and_target(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rows = [
        CrapRow(
            path="pkg/a.py", name="hot", start=1, end=10, ccn=8, loc=10, coverage=0.25, crap=40.0
        )
    ]

    stats_mod._render_crap_actions(rows, verbose=False)

    assert capsys.readouterr().out == (
        "    Cover or simplify hot functions; start with:\n      pkg/a.py::hot  cov 25%\n"
    )


def test_render_crap_actions_limits_rows_with_exact_indent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rows = [
        CrapRow(
            path="pkg/a.py",
            name=f"hot_{index}",
            start=1,
            end=10,
            ccn=8,
            loc=10,
            coverage=0.505,
            crap=40.0,
        )
        for index in range(4)
    ]

    stats_mod._render_crap_actions(rows, verbose=False)

    assert capsys.readouterr().out == (
        "    Cover or simplify hot functions; start with:\n"
        "      pkg/a.py::hot_0  cov 50%\n"
        "      pkg/a.py::hot_1  cov 50%\n"
        "      pkg/a.py::hot_2  cov 50%\n"
        "      … 1 more (use --verbose)\n"
    )


def test_trust_next_actions_explain_missing_mutation_summary() -> None:
    report = TrustReport(
        score=100.0,
        prev_score=None,
        crap_rows=[],
        suspicious=[],
        mutation=None,
        coverage_pct=90.0,
        crap_max=30.0,
        coverage_min=80.0,
        mutation_min_score=60.0,
    )

    actions = {action["kind"]: action for action in stats_mod._trust_next_actions(report)}

    assert actions["mutation"]["message"] == "Run `interlocks gate mutation --min-score=60`."
    assert actions["mutation"]["targets"] == []
    assert "refresh" not in actions


def test_trust_next_actions_explain_stale_mutation_evidence() -> None:
    report = TrustReport(
        score=70.0,
        prev_score=None,
        crap_rows=[],
        suspicious=[],
        mutation=None,
        coverage_pct=94.0,
        crap_max=30.0,
        mutation_min_score=60.0,
        mutation_max_runtime=900,
        mutation_evidence_stale=True,
    )

    actions = {action["kind"]: action for action in stats_mod._trust_next_actions(report)}

    assert actions["mutation"] == {
        "kind": "mutation",
        "message": (
            "Cached mutation evidence is stale after a newer mutmut run; "
            "rerun `interlocks gate mutation --min-score=60 --max-runtime=900`."
        ),
        "targets": [],
    }


def test_trust_next_actions_explain_no_result_mutation_evidence() -> None:
    report = TrustReport(
        score=70.0,
        prev_score=None,
        crap_rows=[],
        suspicious=[],
        mutation=None,
        coverage_pct=94.0,
        crap_max=30.0,
        mutation_min_score=60.0,
        mutation_max_runtime=900,
        mutation_evidence_no_results=True,
    )

    actions = {action["kind"]: action for action in stats_mod._trust_next_actions(report)}

    message = actions["mutation"]["message"]
    assert isinstance(message, str)
    assert "before any mutants were checked" in message
    assert "interlocks gate mutation --changed-only --since=HEAD" in message
    assert actions["mutation"]["targets"] == []


def test_render_does_not_crash_on_empty_report(capsys: pytest.CaptureFixture[str]) -> None:
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


def test_render_healthy_report_does_not_make_survivors_the_verdict(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = TrustReport(
        score=100.0,
        prev_score=None,
        crap_rows=[],
        suspicious=[],
        mutation=MutationSummary(
            killed=100,
            survived=12,
            timeout=0,
            score=60.0,
            survivors=["pkg.mod.fn__mutmut_1"],
        ),
        coverage_pct=93.0,
        crap_max=30.0,
        coverage_min=80.0,
        mutation_min_score=0.0,
    )

    _render(report, verbose=False)
    captured = capsys.readouterr()

    assert "verdict all clear" in captured.out
    assert "surviving mutant" not in captured.out
    assert "mutation 60%" in captured.out


def test_render_verbose_and_truncation(capsys: pytest.CaptureFixture[str]) -> None:
    """Verbose path shows every row; non-verbose truncates with overflow hints."""
    suspicious = [
        TestInspection(
            file="tests/t.py", name=f"test_{i}", loc=10, assert_count=0, trivial_asserts=0
        )
        for i in range(12)
    ]
    # One trivial-assert row to hit the `!= 0` branch of `_format_suspicious`.
    suspicious.append(
        TestInspection(
            file="tests/t.py", name="test_trivial", loc=8, assert_count=2, trivial_asserts=2
        )
    )
    crap_rows = [
        CrapRow(
            path="a.py", name=f"f{i}", start=1, end=10, ccn=10, loc=10, coverage=0.3, crap=50.0 + i
        )
        for i in range(12)
    ]
    report = TrustReport(
        score=40.0,
        prev_score=None,
        crap_rows=crap_rows,
        suspicious=suspicious,
        mutation=None,
        coverage_pct=None,
        crap_max=30.0,
    )

    _render(report, verbose=False)
    non_verbose = capsys.readouterr().out
    assert "more (use --verbose)" in non_verbose  # _print_truncated hint
    assert "Add behavioral assertions" in non_verbose
    assert "Cover or simplify hot functions" in non_verbose
    # Top-3 actions list + more-hint visible.
    assert f"{len(suspicious) - 3} more" in non_verbose
    assert f"{len(crap_rows) - 3} more" in non_verbose

    _render(report, verbose=True)
    verbose = capsys.readouterr().out
    # Every suspicious row rendered; no trailing "more" overflow hint.
    for row in suspicious:
        assert row.name in verbose
    for row in crap_rows:
        assert f"::{row.name}" in verbose
    assert "more (use --verbose)" not in verbose


def test_inspection_dataclass_fields() -> None:
    """Sanity: TestInspection fields line up with AST walker outputs."""
    t = TestInspection(file="a.py", name="test_x", loc=3, assert_count=1, trivial_asserts=0)
    assert t.loc == 3
    assert t.name == "test_x"
