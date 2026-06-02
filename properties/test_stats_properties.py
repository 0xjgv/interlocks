"""Property tests for trust/statistics reporting helpers."""

from __future__ import annotations

import ast
import keyword
import math

from hypothesis import given
from hypothesis import strategies as st

from interlocks.metrics import CrapRow, MutationSummary
from interlocks.tasks import stats
from interlocks.tasks.stats import SUSPICIOUS_MIN_LOC, TestInspection

_ASSERT_STYLES = st.lists(
    st.sampled_from((
        "plain",
        "plain_trivial",
        "self_assert",
        "self_assert_trivial",
        "pytest_raises",
    )),
    max_size=8,
)
_NONNEGATIVE_COUNTS = st.integers(min_value=0, max_value=20)
_PATH = st.from_regex(r"[A-Za-z0-9_./-]{1,30}", fullmatch=True)
_IDENT = st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,20}", fullmatch=True).filter(
    lambda name: not keyword.iskeyword(name)
)
_FINITE_FLOAT = st.floats(
    min_value=-1_000,
    max_value=1_000,
    allow_nan=False,
    allow_infinity=False,
)
_PERCENT_FLOAT = st.floats(
    min_value=0,
    max_value=100,
    allow_nan=False,
    allow_infinity=False,
)


def _expected_assert_counts(styles: list[str]) -> tuple[int, int]:
    assert_count = len(styles)
    trivial = sum(1 for style in styles if style in {"plain_trivial", "self_assert_trivial"})
    return assert_count, trivial


def _statement_for(style: str) -> list[str]:
    if style == "plain":
        return ["    assert value == 1"]
    if style == "plain_trivial":
        return ["    assert True"]
    if style == "self_assert":
        return ["    self.assertEqual(value, 1)"]
    if style == "self_assert_trivial":
        return ["    self.assertTrue(True)"]
    return ["    with pytest.raises(ValueError):", "        raise ValueError()"]


def _function_from_styles(styles: list[str], *, nested_asserts: int) -> ast.FunctionDef:
    lines = ["def test_generated(self):", "    value = 1"]
    for style in styles:
        lines.extend(_statement_for(style))
    if nested_asserts:
        lines.append("    def helper():")
        for _ in range(nested_asserts):
            lines.append("        assert False")
    if not styles and not nested_asserts:
        lines.append("    pass")
    tree = ast.parse("\n".join(lines) + "\n")
    fn = tree.body[0]
    assert isinstance(fn, ast.FunctionDef)
    return fn


@given(styles=_ASSERT_STYLES, nested_asserts=st.integers(min_value=0, max_value=5))
def test_inspect_function_counts_only_same_scope_assertions(
    styles: list[str], nested_asserts: int
) -> None:
    inspected = stats._inspect_function(
        _function_from_styles(styles, nested_asserts=nested_asserts),
        "tests/test_generated.py",
        qualname="TestGenerated.test_generated",
    )

    expected_asserts, expected_trivial = _expected_assert_counts(styles)
    assert inspected.file == "tests/test_generated.py"
    assert inspected.name == "TestGenerated.test_generated"
    assert inspected.assert_count == expected_asserts
    assert inspected.trivial_asserts == expected_trivial
    assert inspected.loc >= 2


@given(styles=_ASSERT_STYLES)
def test_inspect_function_reports_exact_source_span(styles: list[str]) -> None:
    fn = _function_from_styles(styles, nested_asserts=0)

    inspected = stats._inspect_function(
        fn,
        "tests/test_generated.py",
        qualname="test_generated",
    )

    assert inspected.loc == (fn.end_lineno or fn.lineno) - fn.lineno + 1


@given(name=_IDENT)
def test_inspect_function_reports_zero_asserts_for_plain_functions(name: str) -> None:
    fn = ast.parse(f"def {name}() -> None:\n    pass\n").body[0]
    assert isinstance(fn, ast.FunctionDef)

    inspected = stats._inspect_function(fn, "tests/test_generated.py", qualname=name)

    assert inspected.assert_count == 0
    assert inspected.trivial_asserts == 0


@given(names=st.lists(_IDENT, max_size=8, unique=True))
def test_inspect_tree_returns_top_level_and_class_test_functions(names: list[str]) -> None:
    top_level = "\n".join(f"def test_{name}():\n    pass\n" for name in names)
    methods = "\n".join(f"    def test_{name}(self):\n        pass\n" for name in names)
    tree = ast.parse(f"{top_level}\nclass TestGenerated:\n{methods or '    pass'}\n")

    inspected = stats._inspect_tree(tree, "tests/test_generated.py")

    assert {row.file for row in inspected} == {"tests/test_generated.py"} if inspected else True
    assert {row.name for row in inspected} == {
        *(f"test_{name}" for name in names),
        *(f"TestGenerated.test_{name}" for name in names),
    }


@given(names=st.lists(_IDENT, max_size=8, unique=True))
def test_inspect_tree_ignores_non_test_functions(names: list[str]) -> None:
    helpers = "\n".join(f"def helper_{name}():\n    assert False\n" for name in names)
    tree = ast.parse(f"{helpers}\nclass Helper:\n    def helper(self):\n        assert False\n")

    assert stats._inspect_tree(tree, "tests/test_generated.py") == []


@given(
    loc=st.integers(min_value=1, max_value=30),
    assert_count=st.integers(min_value=0, max_value=8),
    trivial_asserts=st.integers(min_value=0, max_value=8),
)
def test_flag_suspicious_matches_assertion_light_contract(
    loc: int, assert_count: int, trivial_asserts: int
) -> None:
    trivial = min(trivial_asserts, assert_count)
    inspection = TestInspection(
        file="tests/test_generated.py",
        name="test_generated",
        loc=loc,
        assert_count=assert_count,
        trivial_asserts=trivial,
    )

    flagged = stats._flag_suspicious([inspection])
    should_flag = loc > SUSPICIOUS_MIN_LOC and assert_count in (0, trivial)
    assert flagged == ([inspection] if should_flag else [])


@given(
    rows=st.lists(
        st.tuples(
            _PATH,
            _IDENT,
            st.integers(min_value=0, max_value=20),
            st.integers(min_value=0, max_value=8),
            st.integers(min_value=0, max_value=8),
        ),
        max_size=20,
    )
)
def test_flag_suspicious_preserves_input_order_for_flagged_rows(
    rows: list[tuple[str, str, int, int, int]],
) -> None:
    inspections = [
        TestInspection(
            file=file,
            name=name,
            loc=loc,
            assert_count=assert_count,
            trivial_asserts=min(trivial_asserts, assert_count),
        )
        for file, name, loc, assert_count, trivial_asserts in rows
    ]

    assert stats._flag_suspicious(inspections) == [
        inspection
        for inspection in inspections
        if inspection.loc > SUSPICIOUS_MIN_LOC
        and inspection.assert_count in (0, inspection.trivial_asserts)
    ]


@given(names=st.lists(_IDENT, max_size=12, unique=True))
def test_flag_suspicious_flags_all_long_tests_without_asserts(names: list[str]) -> None:
    inspections = [
        TestInspection(
            file=f"tests/{name}.py",
            name=name,
            loc=SUSPICIOUS_MIN_LOC + 1,
            assert_count=0,
            trivial_asserts=0,
        )
        for name in names
    ]

    assert stats._flag_suspicious(inspections) == inspections


@given(context_name=_IDENT)
def test_is_pytest_assert_with_matches_supported_pytest_context_managers(
    context_name: str,
) -> None:
    tree = ast.parse(f"with pytest.{context_name}():\n    pass\n")
    node = tree.body[0]
    assert isinstance(node, ast.With)

    assert stats._is_pytest_assert_with(node) is (
        context_name in {"raises", "warns", "deprecated_call"}
    )


@given(
    contexts=st.lists(
        st.sampled_from(["raises", "warns", "deprecated_call", "not_asserting"]),
        min_size=1,
        max_size=6,
    )
)
def test_is_pytest_assert_with_accepts_any_supported_pytest_context(
    contexts: list[str],
) -> None:
    items = ", ".join(f"pytest.{context}()" for context in contexts)
    tree = ast.parse(f"with {items}:\n    pass\n")
    node = tree.body[0]
    assert isinstance(node, ast.With)

    assert stats._is_pytest_assert_with(node) is (
        bool({"raises", "warns", "deprecated_call"} & set(contexts))
    )


@given(
    cov_map=st.dictionaries(
        _PATH,
        st.dictionaries(
            st.integers(min_value=1, max_value=1_000),
            st.integers(min_value=-3, max_value=3),
            max_size=20,
        ),
        max_size=10,
    )
)
def test_coverage_pct_matches_positive_hit_rate(
    cov_map: dict[str, dict[int, int]],
) -> None:
    total = sum(len(lines) for lines in cov_map.values())
    hit = sum(1 for lines in cov_map.values() for value in lines.values() if value > 0)

    result = stats._coverage_pct(cov_map)

    if total == 0:
        assert result is None
    else:
        assert result is not None
        assert math.isclose(result, hit / total * 100)


@given(
    populated=st.dictionaries(
        _PATH,
        st.dictionaries(
            st.integers(min_value=1, max_value=1_000),
            st.integers(min_value=-3, max_value=3),
            min_size=1,
            max_size=20,
        ),
        max_size=10,
    ),
    empty_files=st.lists(_PATH, max_size=10, unique=True),
)
def test_coverage_pct_ignores_empty_tracked_files(
    populated: dict[str, dict[int, int]],
    empty_files: list[str],
) -> None:
    with_empty = {**{path: {} for path in empty_files}, **populated}

    assert stats._coverage_pct(with_empty) == stats._coverage_pct(populated)


@given(score=_FINITE_FLOAT)
def test_tier_selects_expected_score_band(score: float) -> None:
    tier = stats._tier(score)

    if score >= stats.TRUST_GREEN:
        assert tier[3] == "HEALTHY"
    elif score >= stats.TRUST_YELLOW:
        assert tier[3] == "CAUTION"
    else:
        assert tier[3] == "RISKY"


@given(delta=_FINITE_FLOAT)
def test_delta_arrow_matches_delta_sign(delta: float) -> None:
    expected = "\u2191" if delta > 0 else "\u2193" if delta < 0 else "="

    assert stats._delta_arrow(delta) == expected


@given(magnitude=st.floats(min_value=0.001, max_value=1_000, allow_nan=False))
def test_delta_arrow_has_exact_zero_boundary(magnitude: float) -> None:
    assert stats._delta_arrow(magnitude) == "\u2191"
    assert stats._delta_arrow(-magnitude) == "\u2193"
    assert stats._delta_arrow(0.0) == "="


@given(crap=_FINITE_FLOAT, crap_max=_FINITE_FLOAT)
def test_crap_color_matches_threshold_bands(crap: float, crap_max: float) -> None:
    if crap > crap_max + stats.CRAP_RED_MARGIN:
        expected = stats.RED
    elif crap >= crap_max:
        expected = stats.YELLOW
    else:
        expected = stats.GREEN

    assert stats._crap_color(crap, crap_max) == expected


@given(crap_max=_FINITE_FLOAT)
def test_crap_color_keeps_red_boundary_exclusive(crap_max: float) -> None:
    assert stats._crap_color(crap_max - 0.001, crap_max) == stats.GREEN
    assert stats._crap_color(crap_max, crap_max) == stats.YELLOW
    assert stats._crap_color(crap_max + stats.CRAP_RED_MARGIN, crap_max) == stats.YELLOW
    assert stats._crap_color(crap_max + stats.CRAP_RED_MARGIN + 0.001, crap_max) == stats.RED


@given(
    file=_PATH,
    name=_IDENT,
    loc=st.integers(min_value=1, max_value=500),
    assert_count=st.integers(min_value=0, max_value=20),
)
def test_format_suspicious_reports_zero_or_trivial_assert_detail(
    file: str,
    name: str,
    loc: int,
    assert_count: int,
) -> None:
    inspection = TestInspection(
        file=file,
        name=name,
        loc=loc,
        assert_count=assert_count,
        trivial_asserts=assert_count,
    )

    rendered = stats._format_suspicious(inspection)

    assert file in rendered
    assert name in rendered
    assert f"{loc} LOC" in rendered
    assert ("0 asserts" in rendered) is (assert_count == 0)
    assert ("assert(s) (trivial)" in rendered) is (assert_count != 0)


@given(file=_PATH, name=_IDENT, loc=st.integers(min_value=1, max_value=500))
def test_format_suspicious_has_exact_zero_assert_shape(file: str, name: str, loc: int) -> None:
    inspection = TestInspection(file=file, name=name, loc=loc, assert_count=0, trivial_asserts=0)

    assert stats._format_suspicious(inspection) == f"    {file}::{name}  {loc} LOC, 0 asserts"


@given(
    suspicious_count=_NONNEGATIVE_COUNTS,
    crap_count=_NONNEGATIVE_COUNTS,
    mutation_score=_PERCENT_FLOAT,
    mutation_min_score=_PERCENT_FLOAT,
    coverage=st.one_of(st.none(), _PERCENT_FLOAT),
    coverage_min=_PERCENT_FLOAT,
    include_mutation=st.booleans(),
    completed=st.booleans(),
)
def test_verdict_sentence_reports_only_present_risks(
    suspicious_count: int,
    crap_count: int,
    mutation_score: float,
    mutation_min_score: float,
    coverage: float | None,
    coverage_min: float,
    include_mutation: bool,
    completed: bool,
) -> None:
    mutation = (
        MutationSummary(killed=1, survived=1, timeout=0, score=mutation_score, completed=completed)
        if include_mutation
        else None
    )
    sentence = stats._verdict_sentence(
        stats._VerdictSignals(
            suspicious_count=suspicious_count,
            crap_count=crap_count,
            mutation=mutation,
            mutation_min_score=mutation_min_score,
            coverage_pct=coverage,
            coverage_min=coverage_min,
        )
    )
    expect_missing_mutation = not include_mutation and mutation_min_score > 0
    expect_partial_mutation = include_mutation and mutation_min_score > 0 and not completed
    expect_low_mutation = (
        include_mutation
        and mutation_min_score > 0
        and completed
        and mutation_score < mutation_min_score
    )
    expect_low_coverage = coverage is not None and coverage_min > 0 and coverage < coverage_min

    if not any((
        suspicious_count,
        crap_count,
        expect_missing_mutation,
        expect_partial_mutation,
        expect_low_mutation,
        expect_low_coverage,
    )):
        assert sentence == "all clear"
    else:
        assert sentence != "all clear"
    parts = sentence.split(", ") if sentence != "all clear" else []
    assert (f"{suspicious_count} suspicious test(s)" in sentence) is bool(suspicious_count)
    assert (f"{crap_count} hot fn(s)" in sentence) is bool(crap_count)
    assert ("mutation unavailable" in sentence) is expect_missing_mutation
    low_mutation = f"mutation {mutation_score:.0f}% below {mutation_min_score:.0f}%"
    partial_low_mutation = (
        f"partial mutation {mutation_score:.0f}% below {mutation_min_score:.0f}%"
    )
    assert (low_mutation in parts) is expect_low_mutation
    assert (partial_low_mutation in parts or "partial mutation evidence" in parts) is (
        expect_partial_mutation
    )
    assert ("partial mutation" in sentence) is expect_partial_mutation
    assert (
        coverage is not None and f"coverage {coverage:.0f}% below {coverage_min:.0f}%" in sentence
    ) is expect_low_coverage
    assert "surviving mutant" not in sentence


@given(count=_NONNEGATIVE_COUNTS, label=st.sampled_from(("suspicious test(s)", "hot fn(s)")))
def test_count_sentence_reports_only_present_counts(count: int, label: str) -> None:
    sentence = stats._count_sentence(count, label)

    assert sentence == (f"{count} {label}" if count else "")


@given(label=st.text(min_size=1, max_size=40))
def test_count_sentence_omits_zero_counts(label: str) -> None:
    assert stats._count_sentence(0, label) == ""


@given(coverage=st.one_of(st.none(), _PERCENT_FLOAT), coverage_min=_PERCENT_FLOAT)
def test_coverage_gap_sentence_reports_only_configured_shortfalls(
    coverage: float | None, coverage_min: float
) -> None:
    sentence = stats._coverage_gap_sentence(coverage, coverage_min)
    expect_gap = coverage is not None and coverage_min > 0 and coverage < coverage_min

    assert bool(sentence) is expect_gap
    if expect_gap:
        assert sentence == f"coverage {coverage:.0f}% below {coverage_min:.0f}%"


@given(coverage=_PERCENT_FLOAT)
def test_coverage_gap_sentence_omits_equal_or_disabled_floor(coverage: float) -> None:
    assert stats._coverage_gap_sentence(coverage, coverage) == ""
    assert stats._coverage_gap_sentence(coverage, 0.0) == ""
    assert stats._coverage_gap_sentence(None, coverage) == ""


@given(
    include_mutation=st.booleans(),
    mutation_score=_PERCENT_FLOAT,
    mutation_min_score=_PERCENT_FLOAT,
    completed=st.booleans(),
)
def test_mutation_gap_sentence_reports_only_configured_shortfalls(
    include_mutation: bool, mutation_score: float, mutation_min_score: float, completed: bool
) -> None:
    mutation = (
        MutationSummary(killed=1, survived=1, timeout=0, score=mutation_score, completed=completed)
        if include_mutation
        else None
    )
    sentence = stats._mutation_gap_sentence(mutation, mutation_min_score)

    if mutation_min_score <= 0:
        assert not sentence
    elif mutation is None:
        assert sentence == "mutation unavailable"
    elif not completed and mutation_score < mutation_min_score:
        assert (
            sentence == f"partial mutation {mutation_score:.0f}% below {mutation_min_score:.0f}%"
        )
    elif not completed:
        assert sentence == "partial mutation evidence"
    elif mutation_score < mutation_min_score:
        assert sentence == f"mutation {mutation_score:.0f}% below {mutation_min_score:.0f}%"
    else:
        assert not sentence


@given(score=_PERCENT_FLOAT)
def test_mutation_gap_sentence_accepts_exact_floor(score: float) -> None:
    mutation = MutationSummary(killed=1, survived=1, timeout=0, score=score, completed=True)

    assert stats._mutation_gap_sentence(mutation, score) == ""


@given(floor=st.floats(max_value=0, allow_nan=False, allow_infinity=False))
def test_mutation_gap_sentence_disabled_floor_suppresses_missing_mutation(floor: float) -> None:
    assert stats._mutation_gap_sentence(None, floor) == ""


@given(
    score=st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
    coverage=st.one_of(
        st.none(),
        st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
    ),
    suspicious=st.lists(
        st.tuples(_PATH, _IDENT, st.integers(min_value=1, max_value=100), _NONNEGATIVE_COUNTS),
        max_size=8,
    ),
    crap=st.lists(
        st.tuples(
            _PATH,
            _IDENT,
            st.integers(min_value=1, max_value=30),
            st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False),
            st.floats(min_value=0, max_value=300, allow_nan=False, allow_infinity=False),
        ),
        max_size=8,
    ),
)
def test_trust_json_preserves_report_shape(
    score: float,
    coverage: float | None,
    suspicious: list[tuple[str, str, int, int]],
    crap: list[tuple[str, str, int, float, float]],
) -> None:
    report = stats.TrustReport(
        score=score,
        prev_score=None,
        crap_rows=[
            CrapRow(
                path=path,
                name=name,
                start=1,
                end=loc,
                ccn=loc,
                loc=loc,
                coverage=line_coverage,
                crap=crap_score,
            )
            for path, name, loc, line_coverage, crap_score in crap
        ],
        suspicious=[
            TestInspection(path, name, loc, assert_count, assert_count)
            for path, name, loc, assert_count in suspicious
        ],
        mutation=None,
        coverage_pct=coverage,
        crap_max=30.0,
    )

    payload = stats._trust_json(report)

    assert payload["command"] == "trust"
    assert payload["score"] == {"earned": int(score), "max": 100}
    assert payload["verdict"] == stats._tier(score)[3]
    assert payload["coverage_pct"] == (round(coverage) if coverage is not None else None)
    next_actions = payload["next_actions"]
    crap_offenders = payload["crap_offenders"]
    suspicious_tests = payload["suspicious_tests"]
    assert isinstance(next_actions, list)
    assert isinstance(crap_offenders, list)
    assert isinstance(suspicious_tests, list)
    assert len(crap_offenders) == len(crap)
    assert len(suspicious_tests) == len(suspicious)
    action_kinds = [action["kind"] for action in next_actions]
    assert ("suspicious-tests" in action_kinds) is bool(suspicious)
    assert ("crap" in action_kinds) is bool(crap)
    assert "refresh" not in action_kinds


@given(score=_PERCENT_FLOAT)
def test_trust_json_omits_remediation_lists_for_clean_report(score: float) -> None:
    report = stats.TrustReport(
        score=score,
        prev_score=None,
        crap_rows=[],
        suspicious=[],
        mutation=None,
        coverage_pct=None,
        crap_max=30.0,
    )

    payload = stats._trust_json(report)

    assert payload["next_actions"] == []
    assert payload["crap_offenders"] == []
    assert payload["suspicious_tests"] == []


@given(
    suspicious=st.lists(
        st.tuples(_PATH, _IDENT, st.integers(min_value=1, max_value=100), _NONNEGATIVE_COUNTS),
        max_size=8,
    ),
    crap=st.lists(
        st.tuples(
            _PATH,
            _IDENT,
            st.integers(min_value=1, max_value=30),
            st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False),
            st.floats(min_value=0, max_value=300, allow_nan=False, allow_infinity=False),
        ),
        max_size=8,
    ),
)
def test_trust_next_actions_track_available_remediation_targets(
    suspicious: list[tuple[str, str, int, int]],
    crap: list[tuple[str, str, int, float, float]],
) -> None:
    report = stats.TrustReport(
        score=50.0,
        prev_score=None,
        crap_rows=[
            CrapRow(
                path=path,
                name=name,
                start=1,
                end=loc,
                ccn=loc,
                loc=loc,
                coverage=line_coverage,
                crap=crap_score,
            )
            for path, name, loc, line_coverage, crap_score in crap
        ],
        suspicious=[
            TestInspection(path, name, loc, assert_count, assert_count)
            for path, name, loc, assert_count in suspicious
        ],
        mutation=None,
        coverage_pct=50.0,
        crap_max=30.0,
    )

    actions = stats._trust_next_actions(report)
    by_kind = {action["kind"]: action for action in actions}

    assert ("suspicious-tests" in by_kind) is bool(suspicious)
    assert ("crap" in by_kind) is bool(crap)
    assert "refresh" not in by_kind
    if suspicious:
        assert by_kind["suspicious-tests"]["targets"] == [
            f"{path}::{name}" for path, name, _loc, _assert_count in suspicious
        ]
    if crap:
        assert by_kind["crap"]["targets"] == [
            f"{path}::{name}" for path, name, _loc, _coverage, _crap in crap
        ]


@given(
    targets=st.lists(_IDENT, max_size=40),
    kind=_IDENT,
    message=st.text(max_size=120),
)
def test_trust_action_caps_targets_without_losing_count(
    targets: list[str],
    kind: str,
    message: str,
) -> None:
    action = stats._trust_action(kind, message, targets)
    limit = stats.TRUST_ACTION_TARGET_LIMIT

    assert action["kind"] == kind
    assert action["message"] == message
    assert action["targets"] == targets[:limit]
    if len(targets) > limit:
        assert action["omitted_targets"] == len(targets) - limit
    else:
        assert "omitted_targets" not in action


@given(targets=st.lists(_IDENT, max_size=40), kind=_IDENT, message=st.text(max_size=120))
def test_trust_action_copies_target_slice(
    targets: list[str],
    kind: str,
    message: str,
) -> None:
    expected = targets[: stats.TRUST_ACTION_TARGET_LIMIT]
    action = stats._trust_action(kind, message, targets)
    targets.append("mutated-after-action")

    assert action["targets"] == expected


@given(
    mutation_score=st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
    mutation_floor=st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
    coverage=st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
    coverage_floor=st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
    survivors=st.lists(_IDENT, max_size=40),
    completed=st.booleans(),
)
def test_trust_next_actions_explain_threshold_shortfalls(
    mutation_score: float,
    mutation_floor: float,
    coverage: float,
    coverage_floor: float,
    survivors: list[str],
    completed: bool,
) -> None:
    report = stats.TrustReport(
        score=50.0,
        prev_score=None,
        crap_rows=[],
        suspicious=[],
        mutation=MutationSummary(
            killed=1,
            survived=len(survivors),
            timeout=0,
            score=mutation_score,
            survivors=survivors,
            completed=completed,
        ),
        coverage_pct=coverage,
        crap_max=30.0,
        coverage_min=coverage_floor,
        mutation_min_score=mutation_floor,
    )

    actions = {action["kind"]: action for action in stats._trust_next_actions(report)}

    mutation_short = mutation_floor > 0 and (mutation_score < mutation_floor or not completed)
    coverage_short = coverage_floor > 0 and coverage < coverage_floor
    assert ("mutation" in actions) is mutation_short
    assert ("coverage" in actions) is coverage_short
    assert "refresh" not in actions
    if mutation_short:
        if completed:
            assert actions["mutation"]["targets"] == survivors[: stats.TRUST_ACTION_TARGET_LIMIT]
            if len(survivors) > stats.TRUST_ACTION_TARGET_LIMIT:
                assert (
                    actions["mutation"]["omitted_targets"]
                    == len(survivors) - stats.TRUST_ACTION_TARGET_LIMIT
                )
            else:
                assert "omitted_targets" not in actions["mutation"]
        else:
            assert "targets" not in actions["mutation"]
            assert "omitted_targets" not in actions["mutation"]
    if coverage_short:
        assert actions["coverage"]["targets"] == []


@given(
    score=_PERCENT_FLOAT,
    floor=_PERCENT_FLOAT,
    completed=st.booleans(),
    max_runtime=st.integers(min_value=0, max_value=10_000),
)
def test_mutation_action_message_distinguishes_partial_runs(
    score: float, floor: float, completed: bool, max_runtime: int
) -> None:
    mutation = MutationSummary(
        killed=1,
        survived=1,
        timeout=0,
        score=score,
        completed=completed,
    )

    message = stats._mutation_action_message(mutation, floor, max_runtime)

    assert ("timed out" in message) is (completed is False)
    assert f"interlocks mutation --min-score={floor:.0f}" in message
    assert (f"--max-runtime={max_runtime}" in message) is (max_runtime > 0)


@given(floor=_PERCENT_FLOAT, max_runtime=st.integers(min_value=0, max_value=10_000))
def test_mutation_action_message_accepts_missing_summary(
    floor: float,
    max_runtime: int,
) -> None:
    message = stats._mutation_action_message(None, floor, max_runtime)

    assert "timed out" not in message
    assert f"interlocks mutation --min-score={floor:.0f}" in message
    assert (f"--max-runtime={max_runtime}" in message) is (max_runtime > 0)


@given(floor=_PERCENT_FLOAT, max_runtime=st.integers(min_value=0, max_value=10_000))
def test_mutation_action_message_for_partial_summary_requests_more_runtime(
    floor: float,
    max_runtime: int,
) -> None:
    mutation = MutationSummary(killed=1, survived=0, timeout=0, score=100.0, completed=False)

    message = stats._mutation_action_message(mutation, floor, max_runtime)

    assert message.startswith("Last mutation run timed out; rerun `")
    assert "with more runtime" in message


@given(floor=_PERCENT_FLOAT, max_runtime=st.integers(min_value=0, max_value=10_000))
def test_mutation_retry_command_includes_runtime_only_when_positive(
    floor: float,
    max_runtime: int,
) -> None:
    command = stats._mutation_retry_command(floor, max_runtime)

    assert command.startswith(f"interlocks mutation --min-score={floor:.0f}")
    assert (f"--max-runtime={max_runtime}" in command) is (max_runtime > 0)


@given(floor=_PERCENT_FLOAT)
def test_mutation_retry_command_without_runtime_is_exact(floor: float) -> None:
    assert stats._mutation_retry_command(floor, 0) == (
        f"interlocks mutation --min-score={floor:.0f}"
    )


@given(
    floor=st.floats(min_value=1, max_value=100, allow_nan=False, allow_infinity=False),
    max_runtime=st.integers(min_value=0, max_value=10_000),
    stale=st.booleans(),
)
def test_trust_next_actions_prioritize_no_result_mutation_evidence(
    floor: float,
    max_runtime: int,
    stale: bool,
) -> None:
    report = stats.TrustReport(
        score=100.0,
        prev_score=None,
        crap_rows=[],
        suspicious=[],
        mutation=None,
        coverage_pct=None,
        crap_max=30.0,
        mutation_min_score=floor,
        mutation_max_runtime=max_runtime,
        mutation_evidence_stale=stale,
        mutation_evidence_no_results=True,
    )

    actions = {action["kind"]: action for action in stats._trust_next_actions(report)}

    message = actions["mutation"]["message"]
    assert isinstance(message, str)
    assert f"interlocks mutation --min-score={floor:.0f}" in message
    assert (f"--max-runtime={max_runtime}" in message) is (max_runtime > 0)
    assert "--changed-only" in message
    assert "--since=HEAD" in message
    assert "stale" not in message
    assert actions["mutation"]["targets"] == []


@given(json_mode=st.booleans(), no_trend=st.booleans())
def test_trust_refresh_command_preserves_requested_output_shape(
    json_mode: bool, no_trend: bool
) -> None:
    command = stats._trust_refresh_command(json_mode=json_mode, no_trend=no_trend)

    assert command.startswith("interlocks trust --refresh")
    assert ("--json" in command) is json_mode
    assert ("--no-trend" in command) is no_trend


@given(json_mode=st.booleans(), no_trend=st.booleans())
def test_trust_refresh_command_uses_stable_flag_order(
    json_mode: bool,
    no_trend: bool,
) -> None:
    expected = "interlocks trust --refresh"
    if json_mode:
        expected += " --json"
    if no_trend:
        expected += " --no-trend"

    assert stats._trust_refresh_command(json_mode=json_mode, no_trend=no_trend) == expected


def test_trust_refresh_command_without_optional_flags_is_base_command() -> None:
    assert stats._trust_refresh_command(json_mode=False, no_trend=False) == (
        "interlocks trust --refresh"
    )


@given(floor=st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False))
def test_trust_next_actions_prompt_for_missing_mutation_summary(floor: float) -> None:
    report = stats.TrustReport(
        score=100.0,
        prev_score=None,
        crap_rows=[],
        suspicious=[],
        mutation=None,
        coverage_pct=None,
        crap_max=30.0,
        mutation_min_score=floor,
    )

    actions = {action["kind"]: action for action in stats._trust_next_actions(report)}

    should_prompt = floor > 0
    assert ("mutation" in actions) is should_prompt
    assert "refresh" not in actions
    if should_prompt:
        assert actions["mutation"]["targets"] == []
