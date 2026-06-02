"""Property tests for CRAP metric calculations."""

from __future__ import annotations

import json
import os
import string
import xml.etree.ElementTree as ET  # noqa: S405 - local test XML generation
from math import isfinite
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from interlocks import metrics as metrics_mod
from interlocks.metrics import (
    FunctionStats,
    _coverage_line_entry,
    _mutation_evidence_completed,
    _newest_existing_mtime,
    _parse_lizard,
    _parse_results,
    _source_prefix,
    compute_crap_rows,
    coverage_cache_is_stale,
    coverage_inputs,
    coverage_line_rate,
    function_coverage,
    mutation_evidence_is_stale,
    mutation_evidence_no_results,
    newer_than,
    parse_coverage,
    read_mutation_evidence,
    read_mutation_summary,
)

if TYPE_CHECKING:
    from interlocks.config import InterlockConfig

_NAMES = st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,20}", fullmatch=True)
_PATHS = st.from_regex(
    r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,20}(?:/[A-Za-z0-9_][A-Za-z0-9_.-]{0,20}){0,3}\.py",
    fullmatch=True,
)
_XML_INT_ATTR = st.one_of(
    st.none(),
    st.integers(min_value=-1_000_000, max_value=1_000_000).map(str),
    st.text(alphabet=string.ascii_letters + string.digits + "._:- ", max_size=8),
)
_LINE_RATE_ATTR = st.one_of(
    st.none(),
    st.floats(allow_nan=True, allow_infinity=True, width=64).map(repr),
    st.text(alphabet=string.ascii_letters + string.digits + ".+-eE_ ", max_size=16),
)
_REL_DIRS = st.from_regex(
    r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,20}(?:/[A-Za-z0-9_][A-Za-z0-9_.-]{0,20}){0,2}",
    fullmatch=True,
)
_JSON_SCALARS = st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=20))


@given(
    mtimes=st.lists(st.integers(min_value=1, max_value=1_000_000), max_size=12),
    missing=st.integers(min_value=0, max_value=12),
)
def test_newest_existing_mtime_ignores_missing_paths(
    mtimes: list[int],
    missing: int,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        existing: list[Path] = []
        for index, mtime in enumerate(mtimes):
            path = root / f"present-{index}.txt"
            path.write_text("", encoding="utf-8")
            os.utime(path, (mtime, mtime))
            existing.append(path)
        absent = [root / f"missing-{index}.txt" for index in range(missing)]

        newest = _newest_existing_mtime(iter([*absent, *existing]))

    if mtimes:
        assert newest == pytest.approx(max(mtimes))
    else:
        assert newest is None


@given(mtimes=st.lists(st.integers(min_value=1, max_value=1_000_000), min_size=1, max_size=12))
def test_newest_existing_mtime_is_order_independent(mtimes: list[int]) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        paths: list[Path] = []
        for index, mtime in enumerate(mtimes):
            path = root / f"present-{index}.txt"
            path.write_text("", encoding="utf-8")
            os.utime(path, (mtime, mtime))
            paths.append(path)

        newest = _newest_existing_mtime(iter(reversed(paths)))

    assert newest == pytest.approx(max(mtimes))


@given(completed=_JSON_SCALARS)
def test_mutation_evidence_completed_accepts_only_booleans(completed: object) -> None:
    evidence = {"completed": completed}
    expected = completed if isinstance(completed, bool) else None

    assert _mutation_evidence_completed(evidence) is expected


def test_mutation_evidence_completed_returns_none_without_evidence() -> None:
    assert _mutation_evidence_completed(None) is None


@given(value=_JSON_SCALARS)
def test_mutation_evidence_no_results_accepts_only_true_marker(value: object) -> None:
    assert mutation_evidence_no_results({"no_results": value}) is (value is True)
    assert mutation_evidence_no_results(None) is False


@given(payload=st.dictionaries(st.text(max_size=12), _JSON_SCALARS, max_size=8))
def test_read_mutation_evidence_returns_current_json_payload(payload: dict[str, object]) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        evidence = root / ".interlocks" / "mutation.json"
        evidence.parent.mkdir()
        evidence.write_text(json.dumps(payload), encoding="utf-8")

        assert read_mutation_evidence(root) == payload


@given(
    evidence_mtime=st.integers(min_value=1, max_value=1_000_000),
    stats_mtime=st.integers(min_value=1, max_value=1_000_000),
)
def test_mutation_evidence_staleness_tracks_mutmut_stats_mtime(
    evidence_mtime: int,
    stats_mtime: int,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        evidence = root / ".interlocks" / "mutation.json"
        evidence.parent.mkdir()
        evidence.write_text("{}", encoding="utf-8")
        stats = root / "mutants" / "mutmut-stats.json"
        stats.parent.mkdir()
        stats.write_text("{}", encoding="utf-8")
        os.utime(evidence, (evidence_mtime, evidence_mtime))
        os.utime(stats, (stats_mtime, stats_mtime))

        stale = mutation_evidence_is_stale(root)

    assert stale is (evidence_mtime < stats_mtime)


@given(
    file_mtime=st.integers(min_value=1, max_value=1_000_000),
    threshold=st.integers(min_value=0, max_value=1_000_001),
)
def test_newer_than_matches_strict_file_mtime(
    file_mtime: int,
    threshold: int,
) -> None:
    with TemporaryDirectory() as raw_root:
        path = Path(raw_root) / "sample.py"
        path.write_text("", encoding="utf-8")
        os.utime(path, (file_mtime, file_mtime))

        assert newer_than(path, threshold) is (file_mtime > threshold)
        assert not newer_than(Path(raw_root) / "missing.py", threshold)


@given(
    src_count=st.integers(min_value=0, max_value=3),
    test_count=st.integers(min_value=0, max_value=3),
    property_count=st.integers(min_value=0, max_value=3),
)
def test_coverage_inputs_include_source_test_and_property_python_files(
    src_count: int, test_count: int, property_count: int
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        pyproject = root / "pyproject.toml"
        pyproject.write_text("[project]\nname = 'pkg'\n", encoding="utf-8")
        dirs = {
            "src_dir": (root / "pkg", src_count),
            "test_dir": (root / "tests", test_count),
            "properties_dir": (root / "properties", property_count),
        }
        expected = {pyproject}
        for dirname, (directory, count) in dirs.items():
            directory.mkdir()
            (directory / "ignored.txt").write_text("", encoding="utf-8")
            for index in range(count):
                path = directory / f"test_{dirname}_{index}.py"
                path.write_text("", encoding="utf-8")
                expected.add(path)
        cfg = SimpleNamespace(
            project_root=root,
            src_dir=dirs["src_dir"][0],
            test_dir=dirs["test_dir"][0],
            properties_dir=dirs["properties_dir"][0],
        )

        assert set(coverage_inputs(cast("InterlockConfig", cfg))) == expected


@given(file_mtime=st.integers(min_value=2, max_value=1_000_000))
def test_coverage_cache_is_stale_when_property_tests_are_newer(file_mtime: int) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        cov = root / ".coverage"
        cov.write_text("", encoding="utf-8")
        os.utime(cov, (file_mtime - 1, file_mtime - 1))
        properties = root / "properties"
        properties.mkdir()
        prop = properties / "test_example_properties.py"
        prop.write_text("", encoding="utf-8")
        os.utime(prop, (file_mtime, file_mtime))
        cfg = SimpleNamespace(
            project_root=root,
            src_dir=root / "pkg",
            test_dir=root / "tests",
            properties_dir=properties,
        )

        assert coverage_cache_is_stale(cov, cast("InterlockConfig", cfg))


@given(
    ccn=st.integers(min_value=1, max_value=50),
    hits=st.lists(st.integers(min_value=0, max_value=3), min_size=1, max_size=40),
)
def test_crap_score_is_bounded_by_complexity(ccn: int, hits: list[int]) -> None:
    fn = FunctionStats(
        path="pkg/mod.py",
        name="target",
        start=1,
        end=len(hits),
        nloc=len(hits),
        ccn=ccn,
        args=0,
    )
    cov_map = {"pkg/mod.py": dict(enumerate(hits, start=1))}

    [row] = compute_crap_rows([fn], cov_map)

    assert 0 <= row.coverage <= 1
    assert row.crap >= ccn
    if all(hit > 0 for hit in hits):
        assert row.coverage == 1
        assert row.crap == pytest.approx(ccn)


@given(
    hits=st.dictionaries(
        keys=st.integers(min_value=1, max_value=25),
        values=st.integers(min_value=0, max_value=3),
        max_size=25,
    ),
    start=st.integers(min_value=1, max_value=25),
    end=st.integers(min_value=1, max_value=25),
)
def test_function_coverage_stays_in_unit_interval(
    hits: dict[int, int], start: int, end: int
) -> None:
    lo, hi = sorted((start, end))

    coverage = function_coverage(hits, lo, hi)

    assert 0 <= coverage <= 1


@given(
    hits=st.dictionaries(
        keys=st.integers(min_value=-100, max_value=100),
        values=st.integers(min_value=-3, max_value=3),
        max_size=50,
    ),
    start=st.integers(min_value=-120, max_value=120),
    end=st.integers(min_value=-120, max_value=120),
)
def test_function_coverage_matches_executable_line_hit_ratio(
    hits: dict[int, int], start: int, end: int
) -> None:
    executable_hits = [hit for number, hit in hits.items() if start <= number <= end]
    expected = (
        sum(1 for hit in executable_hits if hit > 0) / len(executable_hits)
        if executable_hits
        else 0.0
    )

    assert function_coverage(hits, start, end) == pytest.approx(expected)


@given(start=st.integers(min_value=1, max_value=100), width=st.integers(min_value=0, max_value=20))
def test_function_coverage_without_executable_lines_is_zero(start: int, width: int) -> None:
    assert function_coverage({}, start, start + width) == 0.0


@given(
    ccn=st.integers(min_value=1, max_value=50),
    hits=st.lists(st.integers(min_value=0, max_value=1), min_size=1, max_size=25),
    threshold_delta=st.floats(min_value=0.1, max_value=10, allow_nan=False),
)
def test_crap_threshold_filter_is_strict(
    ccn: int, hits: list[int], threshold_delta: float
) -> None:
    fn = FunctionStats(
        path="pkg/mod.py",
        name="target",
        start=1,
        end=len(hits),
        nloc=len(hits),
        ccn=ccn,
        args=0,
    )
    cov_map = {"pkg/mod.py": dict(enumerate(hits, start=1))}
    [row] = compute_crap_rows([fn], cov_map)

    assert compute_crap_rows([fn], cov_map, max_crap=row.crap) == []
    assert compute_crap_rows([fn], cov_map, max_crap=row.crap - threshold_delta)


@given(path=_PATHS, ccn=st.integers(min_value=1, max_value=50))
def test_compute_crap_rows_exact_empty_coverage_key_wins_over_stripped_fallback(
    path: str, ccn: int
) -> None:
    fn = FunctionStats(
        path=f"./{path}",
        name="target",
        start=1,
        end=3,
        nloc=3,
        ccn=ccn,
        args=0,
    )
    rows = compute_crap_rows([fn], {fn.path: {}, path: {1: 1, 2: 1, 3: 1}})

    assert rows[0].coverage == 0.0
    assert rows[0].crap == pytest.approx((ccn * ccn) + ccn)


@given(number=_XML_INT_ATTR, hits=_XML_INT_ATTR)
def test_coverage_line_entry_accepts_only_parseable_line_rows(
    number: str | None, hits: str | None
) -> None:
    line = ET.Element("line")
    if number is not None:
        line.set("number", number)
    if hits is not None:
        line.set("hits", hits)

    parsed = _coverage_line_entry(line)

    try:
        expected_number = int(number) if number else None
        expected_hits = int(hits) if hits is not None else 0
    except ValueError:
        assert parsed is None
        return
    if expected_number is None:
        assert parsed is None
    else:
        assert parsed == (expected_number, expected_hits)


@given(rows=st.lists(st.tuples(_XML_INT_ATTR, _XML_INT_ATTR), max_size=20))
def test_parse_coverage_ignores_malformed_line_rows(
    rows: list[tuple[str | None, str | None]],
) -> None:
    with TemporaryDirectory() as raw_root:
        root = ET.Element("coverage")
        packages = ET.SubElement(root, "packages")
        classes = ET.SubElement(packages, "classes")
        class_node = ET.SubElement(classes, "class")
        class_node.set("filename", "pkg/mod.py")
        lines_node = ET.SubElement(class_node, "lines")
        expected: dict[int, int] = {}
        for number, hits in rows:
            line = ET.SubElement(lines_node, "line")
            if number is not None:
                line.set("number", number)
            if hits is not None:
                line.set("hits", hits)
            parsed = _coverage_line_entry(line)
            if parsed is not None:
                line_number, hit_count = parsed
                expected[line_number] = hit_count
        path = Path(raw_root) / "coverage.xml"
        ET.ElementTree(root).write(path, encoding="utf-8")

        assert parse_coverage(path) == {"pkg/mod.py": expected}


@given(filename=st.sampled_from(["mod.py", "pkg/mod.py"]))
def test_parse_coverage_prefixes_source_relative_filenames_once(filename: str) -> None:
    with TemporaryDirectory() as raw_root:
        old_cwd = Path.cwd()
        root_path = Path(raw_root)
        package = root_path / "pkg"
        package.mkdir()
        root = ET.Element("coverage")
        sources = ET.SubElement(root, "sources")
        source = ET.SubElement(sources, "source")
        source.text = str(package)
        packages = ET.SubElement(root, "packages")
        classes = ET.SubElement(packages, "classes")
        class_node = ET.SubElement(classes, "class")
        class_node.set("filename", filename)
        lines_node = ET.SubElement(class_node, "lines")
        line = ET.SubElement(lines_node, "line")
        line.set("number", "7")
        line.set("hits", "1")
        path = root_path / "coverage.xml"
        ET.ElementTree(root).write(path, encoding="utf-8")
        os.chdir(root_path)
        try:
            parsed = parse_coverage(path)
        finally:
            os.chdir(old_cwd)

    assert parsed == {"pkg/mod.py": {7: 1}}


@given(rate=_LINE_RATE_ATTR)
def test_coverage_line_rate_accepts_only_unit_interval_rates(rate: str | None) -> None:
    with TemporaryDirectory() as raw_root:
        root = ET.Element("coverage")
        if rate is not None:
            root.set("line-rate", rate)
        path = Path(raw_root) / "coverage.xml"
        ET.ElementTree(root).write(path, encoding="utf-8")

        parsed = coverage_line_rate(path)

        if rate is None:
            assert parsed is None
            return
        try:
            expected = float(rate)
        except ValueError:
            assert parsed is None
            return
        if isfinite(expected) and 0.0 <= expected <= 1.0:
            assert parsed == pytest.approx(expected)
        else:
            assert parsed is None


@given(prefix=_REL_DIRS, leading_blank=st.booleans(), include_outside=st.booleans())
def test_source_prefix_returns_first_nonblank_source_under_cwd(
    prefix: str,
    leading_blank: bool,
    include_outside: bool,
) -> None:
    old_cwd = Path.cwd()
    with TemporaryDirectory() as raw_root, TemporaryDirectory() as raw_outside:
        root_dir = Path(raw_root)
        source_dir = root_dir / prefix
        source_dir.mkdir(parents=True, exist_ok=True)
        outside_dir = Path(raw_outside)
        coverage = ET.Element("coverage")
        sources = ET.SubElement(coverage, "sources")
        if leading_blank:
            ET.SubElement(sources, "source").text = "  "
        if include_outside:
            ET.SubElement(sources, "source").text = str(outside_dir)
        ET.SubElement(sources, "source").text = str(source_dir)

        os.chdir(root_dir)
        try:
            parsed = _source_prefix(coverage)
        finally:
            os.chdir(old_cwd)

    assert parsed == Path(prefix).as_posix()


@given(include_blank=st.booleans())
def test_source_prefix_returns_empty_without_source_under_cwd(include_blank: bool) -> None:
    old_cwd = Path.cwd()
    with TemporaryDirectory() as raw_root, TemporaryDirectory() as raw_outside:
        root_dir = Path(raw_root)
        coverage = ET.Element("coverage")
        sources = ET.SubElement(coverage, "sources")
        if include_blank:
            ET.SubElement(sources, "source").text = "  "
        ET.SubElement(sources, "source").text = str(Path(raw_outside))

        os.chdir(root_dir)
        try:
            parsed = _source_prefix(coverage)
        finally:
            os.chdir(old_cwd)

    assert not parsed


@given(
    nloc=st.integers(min_value=0, max_value=10_000),
    ccn=st.integers(min_value=0, max_value=1_000),
    args=st.integers(min_value=0, max_value=100),
    name=_NAMES,
    start=st.integers(min_value=1, max_value=10_000),
    length=st.integers(min_value=0, max_value=1_000),
    path=_PATHS,
)
def test_parse_lizard_extracts_generated_rows(
    nloc: int,
    ccn: int,
    args: int,
    name: str,
    start: int,
    length: int,
    path: str,
) -> None:
    end = start + length
    stdout = f"{nloc} {ccn} 123 {args} 456 {name}@{start}-{end}@{path}\n"

    assert _parse_lizard(stdout) == [
        FunctionStats(path=path, name=name, start=start, end=end, nloc=nloc, ccn=ccn, args=args)
    ]


@given(
    before_name=_NAMES,
    after_name=_NAMES,
    start=st.integers(min_value=1, max_value=10_000),
    path=_PATHS,
)
def test_parse_lizard_ignores_rows_after_warnings_block(
    before_name: str,
    after_name: str,
    start: int,
    path: str,
) -> None:
    before = f"10 2 50 1 10 {before_name}@{start}-{start + 3}@{path}"
    after = f"20 4 50 2 10 {after_name}@{start + 10}-{start + 13}@{path}"
    stdout = f"{before}\n!!!! Warnings !!!!\n{after}\n"

    assert _parse_lizard(stdout) == [
        FunctionStats(
            path=path,
            name=before_name,
            start=start,
            end=start + 3,
            nloc=10,
            ccn=2,
            args=1,
        )
    ]


@given(rows=st.lists(st.tuples(_NAMES, _PATHS), max_size=12))
def test_parse_lizard_preserves_valid_row_order_through_noise(
    rows: list[tuple[str, str]],
) -> None:
    stdout = "\n".join(
        f"noise {index}\n10 2 50 1 10 {name}@{index + 1}-{index + 3}@{path}"
        for index, (name, path) in enumerate(rows)
    )

    parsed = _parse_lizard(stdout)

    assert [(row.name, row.path) for row in parsed] == rows


@given(st.text(max_size=2_000))
def test_parse_mutmut_results_never_returns_non_mutant_keys(stdout: str) -> None:
    parsed = _parse_results(stdout)

    assert all("__mutmut_" in key for keys in parsed.values() for key in keys)


@given(
    rows=st.lists(
        st.tuples(
            _NAMES.map(lambda name: f"interlocks.pkg.{name}__mutmut_1"),
            st.sampled_from(["killed", "survived", "timeout", "suspicious"]),
        ),
        max_size=20,
    )
)
def test_parse_mutmut_results_groups_generated_rows(rows: list[tuple[str, str]]) -> None:
    stdout = "".join(f"{key}: {status}\n" for key, status in rows)
    expected: dict[str, list[str]] = {}
    for key, status in rows:
        expected.setdefault(status, []).append(key)

    assert _parse_results(stdout) == expected


@given(
    key=_NAMES.map(lambda name: f"interlocks.pkg.{name}__mutmut_1"),
    status=st.text(
        alphabet=st.characters(blacklist_categories=("Cc", "Cs")),
        min_size=1,
        max_size=40,
    ).filter(lambda value: bool(value.strip())),
)
def test_parse_mutmut_results_strips_outer_whitespace_only(
    key: str,
    status: str,
) -> None:
    assert _parse_results(f"  {key}: {status}  \n") == {status.rstrip(): [key]}


@given(
    rows=st.lists(
        st.tuples(
            _NAMES.map(lambda name: f"interlocks.pkg.{name}__mutmut_1"),
            st.sampled_from(["killed", "survived", "timeout"]),
        ),
        max_size=30,
    )
)
def test_read_mutation_summary_counts_cached_mutmut_results(rows: list[tuple[str, str]]) -> None:
    stdout = "".join(f"{key}: {status}\n" for key, status in rows)
    commands: list[list[str]] = []

    class Cfg:
        def tool_version(self, name: str) -> str:
            assert name == "interlocks-mutmut"
            return "1.2.3"

    def fake_capture(cmd: list[str]) -> SimpleNamespace:
        commands.append(cmd)
        return SimpleNamespace(stdout=stdout)

    old_capture = metrics_mod.capture
    old_load_config = metrics_mod.load_config
    old_cwd = Path.cwd()
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        (root / "mutants").mkdir()
        os.chdir(root)
        metrics_mod.capture = fake_capture  # type: ignore[assignment]
        metrics_mod.load_config = Cfg  # type: ignore[assignment]
        try:
            summary = read_mutation_summary(require_interlocks_evidence=False)
        finally:
            metrics_mod.capture = old_capture
            metrics_mod.load_config = old_load_config
            os.chdir(old_cwd)

    killed = sum(1 for _key, status in rows if status == "killed")
    survived = [key for key, status in rows if status == "survived"]
    timeout = sum(1 for _key, status in rows if status == "timeout")
    total = killed + len(survived) + timeout
    if total == 0:
        assert summary is None
        return
    assert summary is not None
    assert summary.killed == killed
    assert summary.survived == len(survived)
    assert summary.timeout == timeout
    assert summary.survivors == survived
    assert summary.score == pytest.approx(killed / total * 100)
    assert commands
    assert "interlocks-mutmut==1.2.3" in commands[0]


@given(require_interlocks_evidence=st.booleans())
def test_read_mutation_summary_without_cache_dirs_does_not_touch_tools(
    require_interlocks_evidence: bool,
) -> None:
    def fail_unexpected_call(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("read_mutation_summary should return before tool access")

    old_capture = metrics_mod.capture
    old_load_config = metrics_mod.load_config
    old_cwd = Path.cwd()
    with TemporaryDirectory() as raw_root:
        os.chdir(raw_root)
        metrics_mod.capture = fail_unexpected_call  # type: ignore[assignment]
        metrics_mod.load_config = fail_unexpected_call  # type: ignore[assignment]
        try:
            summary = read_mutation_summary(
                require_interlocks_evidence=require_interlocks_evidence
            )
        finally:
            metrics_mod.capture = old_capture
            metrics_mod.load_config = old_load_config
            os.chdir(old_cwd)

    assert summary is None
