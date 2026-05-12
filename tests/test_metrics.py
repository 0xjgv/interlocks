"""Unit tests for interlocks.metrics — shared quality-data readers."""

from __future__ import annotations

import subprocess
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest

from interlocks import metrics as metrics_mod
from interlocks.metrics import (
    FunctionStats,
    _parse_lizard,
    _parse_results,
    compute_crap_rows,
    coverage_line_rate,
    function_coverage,
    parse_coverage,
)

# ─────────────── _parse_lizard ────────────────────────────────────

# lizard columns: NLOC, CCN, token, PARAM (arg count), length, location
_LIZARD_SAMPLE = "      12      3       40       2       14  my_func@10-24@pkg/mod.py\n"


def test_parse_lizard_extracts_fields() -> None:
    rows = _parse_lizard(_LIZARD_SAMPLE)
    assert len(rows) == 1
    fn = rows[0]
    assert fn == FunctionStats(
        path="pkg/mod.py", name="my_func", start=10, end=24, nloc=12, ccn=3, args=2
    )


def test_parse_lizard_loc_property() -> None:
    fn = _parse_lizard(_LIZARD_SAMPLE)[0]
    assert fn.loc == 15  # 24 - 10 + 1


def test_parse_lizard_ignores_non_matching_lines() -> None:
    noise = "Total cc:\nFunction cyclomatic_complexity:\n" + _LIZARD_SAMPLE
    rows = _parse_lizard(noise)
    assert len(rows) == 1


def test_parse_lizard_empty_input() -> None:
    assert _parse_lizard("") == []


# ─────────────── function_coverage ─────────────────────────────────


def test_function_coverage_all_hit() -> None:
    assert function_coverage({10: 1, 11: 1, 12: 1}, 10, 12) == 1.0


def test_function_coverage_none_hit() -> None:
    assert function_coverage({10: 0, 11: 0, 12: 0}, 10, 12) == 0.0


def test_function_coverage_partial() -> None:
    assert function_coverage({10: 1, 11: 0, 12: 1}, 10, 12) == pytest.approx(2 / 3)


def test_function_coverage_empty_range() -> None:
    """Lines outside the cov map → 0.0 rather than raising."""
    assert function_coverage({}, 10, 12) == 0.0


# ─────────────── compute_crap_rows ─────────────────────────────────


def _fn(path: str, ccn: int, start: int = 1, end: int = 10) -> FunctionStats:
    return FunctionStats(
        path=path, name="f", start=start, end=end, nloc=end - start + 1, ccn=ccn, args=1
    )


def test_compute_crap_rows_reader_mode_returns_all() -> None:
    """max_crap=None → every function emitted regardless of score."""
    fns = [_fn("a.py", ccn=1)]
    cov_map = {"a.py": dict.fromkeys(range(1, 11), 1)}  # fully covered
    rows = compute_crap_rows(fns, cov_map)
    assert len(rows) == 1
    assert rows[0].crap == 1  # ccn^2*(1-1)^3 + ccn = 0 + 1


def test_compute_crap_rows_gate_mode_filters_below_threshold() -> None:
    """max_crap=5 → only rows strictly above emit."""
    fns = [_fn("a.py", ccn=1), _fn("b.py", ccn=10, start=1, end=20)]
    cov_map = {"a.py": dict.fromkeys(range(1, 11), 1), "b.py": dict.fromkeys(range(1, 21), 0)}
    rows = compute_crap_rows(fns, cov_map, max_crap=5.0)
    # a: crap=1 (below); b: crap=100+10=110 (above)
    assert len(rows) == 1
    assert rows[0].path == "b.py"


def test_compute_crap_rows_changed_filter() -> None:
    fns = [_fn("a.py", ccn=1), _fn("b.py", ccn=1)]
    cov_map = {"a.py": {}, "b.py": {}}
    rows = compute_crap_rows(fns, cov_map, changed={"a.py"})
    assert {r.path for r in rows} == {"a.py"}


# ─────────────── parse_coverage ────────────────────────────────────

_COVERAGE_XML = textwrap.dedent(
    """\
    <?xml version="1.0" ?>
    <coverage line-rate="0.83">
      <sources><source>/tmp</source></sources>
      <packages><package><classes>
        <class filename="pkg/mod.py">
          <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="0"/>
            <line number="3" hits="2"/>
          </lines>
        </class>
      </classes></package></packages>
    </coverage>
    """
)


def test_parse_coverage_happy_path(tmp_path: Path) -> None:
    cov_file = tmp_path / "coverage.xml"
    cov_file.write_text(_COVERAGE_XML, encoding="utf-8")
    result = parse_coverage(cov_file)
    assert result == {"pkg/mod.py": {1: 1, 2: 0, 3: 2}}


# ─────────────── coverage_line_rate ────────────────────────────────


@pytest.fixture
def primed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[str], Path]:
    """Write `.coverage` + `coverage.xml`, stub regeneration. Returns writer."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".coverage").write_text("", encoding="utf-8")
    xml = tmp_path / "coverage.xml"
    monkeypatch.setattr(metrics_mod, "generate_coverage_xml", lambda: xml)

    def _write(body: str) -> Path:
        xml.write_text(body, encoding="utf-8")
        return xml

    return _write


def test_coverage_line_rate_none_when_dotcoverage_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert coverage_line_rate() is None


def test_coverage_line_rate_returns_float(primed: Callable[[str], Path]) -> None:
    primed('<?xml version="1.0" ?><coverage line-rate="0.83"></coverage>')
    assert coverage_line_rate() == pytest.approx(0.83)


def test_coverage_line_rate_none_when_xml_unparseable(primed: Callable[[str], Path]) -> None:
    primed("not xml")
    assert coverage_line_rate() is None


def test_coverage_line_rate_none_when_line_rate_missing(primed: Callable[[str], Path]) -> None:
    primed('<?xml version="1.0" ?><coverage></coverage>')
    assert coverage_line_rate() is None


def test_coverage_line_rate_reads_explicit_path(tmp_path: Path) -> None:
    """Passing ``cov_file`` bypasses the ``.coverage`` check + regeneration."""
    xml = tmp_path / "coverage.xml"
    xml.write_text('<?xml version="1.0" ?><coverage line-rate="0.5"></coverage>', encoding="utf-8")
    assert coverage_line_rate(xml) == pytest.approx(0.5)


# ─────────────── _parse_results ─────────────────────


def test_read_mutation_summary_uses_pinned_interlocks_mutmut(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Cfg:
        def tool_version(self, name: str) -> str:
            assert name == "interlocks-mutmut"
            return "9.9.9"

    commands: list[list[str]] = []

    def fake_capture(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        return subprocess.CompletedProcess(
            cmd,
            0,
            "interlocks.a.x__mutmut_1: killed\ninterlocks.a.x__mutmut_2: survived\n",
            "",
        )

    monkeypatch.chdir(tmp_path)
    (tmp_path / "mutants").mkdir()
    monkeypatch.setattr(metrics_mod, "load_config", _Cfg)
    monkeypatch.setattr(metrics_mod, "capture", fake_capture)

    summary = metrics_mod.read_mutation_summary()

    assert summary is not None
    assert summary.score == 50.0
    assert "interlocks-mutmut==9.9.9" in commands[0]
    assert commands[0][-3:] == ["mutmut", "results", "--all=true"]


def test_parse_results_groups_by_status() -> None:
    stdout = (
        "    interlocks.a.x__mutmut_1: killed\n"
        "    interlocks.a.x__mutmut_2: survived\n"
        "    interlocks.b.x__mutmut_3: killed\n"
        "    interlocks.c.x__mutmut_4: timeout\n"
    )
    assert _parse_results(stdout) == {
        "killed": ["interlocks.a.x__mutmut_1", "interlocks.b.x__mutmut_3"],
        "survived": ["interlocks.a.x__mutmut_2"],
        "timeout": ["interlocks.c.x__mutmut_4"],
    }


def test_parse_results_ignores_lines_without_mutant_key() -> None:
    stdout = "Total: 42\n    interlocks.a.x__mutmut_1: killed\nsome other: line without key\n"
    assert _parse_results(stdout) == {"killed": ["interlocks.a.x__mutmut_1"]}


def test_parse_results_ignores_lines_without_separator() -> None:
    assert _parse_results("interlocks.a.x__mutmut_1\n") == {}


def test_parse_results_splits_on_first_colon_space_only() -> None:
    stdout = "interlocks.a.x__mutmut_1: killed: detail\n"
    assert _parse_results(stdout) == {"killed: detail": ["interlocks.a.x__mutmut_1"]}


def test_parse_results_empty_input() -> None:
    assert _parse_results("") == {}
