"""Property tests for property-candidate ranking helpers."""

from __future__ import annotations

import ast
import keyword
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given
from hypothesis import strategies as st

from interlocks.config import InterlockConfig
from interlocks.tasks.property_candidates import (
    PropertyCandidate,
    _add_name_signal,
    _add_strategy_signals,
    _candidate_from_function,
    _candidate_function_items,
    _candidate_function_nodes,
    _candidate_summary_line,
    _candidates_from_tree,
    _CandidateSignals,
    _caution_line,
    _child_reference,
    _empty_candidate_lines,
    _filter_by_max_property_refs,
    _has_property_decorator,
    _iter_source_files,
    _known_side_effect_call,
    _local_helper_reference_map,
    _looks_like_class_symbol,
    _max_property_refs,
    _module_relpath,
    _node_side_effect_cautions,
    _property_attribute_symbols,
    _property_attribute_symbols_from_tree,
    _property_candidates_error_payload,
    _property_candidates_json,
    _property_candidates_usage,
    _property_reference_counts,
    _property_references_from_tree,
    _property_refs_line,
    _PropertyCandidatesState,
    _record_import_aliases,
    _record_import_from_aliases,
    _record_instance_aliases,
    _record_unique_alias,
    _reference_aliases,
    _reference_for_module_parts,
    _ReferenceAliases,
    _resolved_reference,
    _resolved_references,
    _scope_reference_aliases,
    _side_effect_cautions,
    _strategies_for_args,
    _strategy_for_annotation,
    _strategy_line,
    property_candidates,
)

_IDENT = st.from_regex(r"[a-zA-Z_][a-zA-Z0-9_]{0,20}", fullmatch=True).filter(
    lambda value: not keyword.iskeyword(value) and value != "module"
)
_STRATEGY_TEXT = st.text(
    alphabet=st.characters(blacklist_characters="\r\n"),
    max_size=20,
).filter(lambda value: value != "tmp_path-derived Path")
_SIDE_EFFECT_METHOD = st.sampled_from([
    "chmod",
    "close",
    "mkdir",
    "open",
    "replace",
    "read_bytes",
    "read_text",
    "rmdir",
    "symlink_to",
    "touch",
    "unlink",
    "write",
    "write_bytes",
    "write_text",
])
_UI_OUTPUT_METHOD = st.sampled_from([
    "banner",
    "command_banner",
    "command_footer",
    "gate_row",
    "group_header",
    "kv_block",
    "message_list",
    "print_json",
    "row",
    "section",
    "stage_footer",
])
_ANNOTATIONS = st.sampled_from([
    ("raw", "str", "st.text()"),
    ("count", "int", "st.integers()"),
    ("ratio", "float", "st.floats(allow_nan=False)"),
    ("enabled", "bool", "st.booleans()"),
    ("items", "list[str]", "st.lists(...)"),
    ("path", "Path", "tmp_path-derived Path"),
])


def _function(source: str) -> ast.FunctionDef:
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.FunctionDef)
    return node


@given(st.sampled_from(["int", "builtins.int", "float", "str", "bool"]))
def test_strategy_for_exact_scalar_annotations(annotation: str) -> None:
    expected = {
        "int": "st.integers()",
        "builtins.int": "st.integers()",
        "float": "st.floats(allow_nan=False)",
        "str": "st.text()",
        "bool": "st.booleans()",
    }[annotation.removeprefix("builtins.")]

    assert _strategy_for_annotation(annotation) == expected


@given(st.sampled_from(["list [ str ]", "Sequence[int]", "dict [ str, int ]", "Mapping[str,int]"]))
def test_strategy_for_collection_annotations_ignores_spaces(annotation: str) -> None:
    strategy = _strategy_for_annotation(annotation)

    assert strategy in {"st.lists(...)", "st.dictionaries(...)"}


@given(method=_SIDE_EFFECT_METHOD)
def test_side_effect_cautions_detect_pathlike_resource_methods(method: str) -> None:
    node = _function(f"def parse_path(path: Path) -> str:\n    path.{method}()\n    return ''\n")

    assert any(f"path.{method}" in caution for caution in _side_effect_cautions(node))


@given(method=_UI_OUTPUT_METHOD)
def test_side_effect_cautions_detect_ui_output_methods(method: str) -> None:
    node = _function(
        f"def format_output(raw: str) -> str:\n    ui.{method}(raw)\n    return raw\n"
    )

    assert any(f"ui.{method}" in caution for caution in _side_effect_cautions(node))


@given(method=st.sampled_from(["is_json", "is_verbose", "use_color"]))
def test_side_effect_cautions_ignore_ui_query_methods(method: str) -> None:
    node = _function(f"def detect_ui() -> bool:\n    return ui.{method}()\n")

    assert _side_effect_cautions(node) == []


@given(name=_IDENT)
def test_side_effect_cautions_detect_global_state_mutation(name: str) -> None:
    node = _function(
        f"def configure(raw: str) -> str:\n    global {name}\n    {name} = raw\n    return raw\n"
    )

    assert "mutates global state" in _side_effect_cautions(node)


@given(
    module=st.sampled_from(["os", "subprocess", "shutil", "signal", "sys"]),
    attr=_IDENT,
)
def test_side_effect_cautions_detect_system_module_assignment(module: str, attr: str) -> None:
    node = _function(
        f"def patch_system(raw: str) -> str:\n    {module}.{attr} = raw\n    return raw\n"
    )

    assert any(
        f"system boundary assignment: {module}.{attr}" == caution
        for caution in _side_effect_cautions(node)
    )


@given(method=st.sampled_from(["apply_many_with_verify", "apply_many_candidates_with_verify"]))
def test_side_effect_cautions_detect_verify_apply_boundaries(method: str) -> None:
    node = _function(
        f"def apply_boundary(raw: str) -> str:\n    verify.{method}()\n    return raw\n"
    )

    assert any(f"verify.{method}" in caution for caution in _side_effect_cautions(node))


@given(
    call=st.sampled_from([
        ("apply_format('sample.py')", "apply_format"),
        ("apply_rule('I001', ('sample.py',))", "apply_rule"),
        ("BrowserTransport.submit(payload)", "BrowserTransport.submit"),
        ("_apply_candidate_batch(candidates, applied, snapshot)", "_apply_candidate_batch"),
        ("_snapshot(files)", "_snapshot"),
        ("_verify_candidate_batch(cmd, applied, snapshot)", "_verify_candidate_batch"),
        ("capture([])", "capture"),
        ("diff.author_edit_cost(base)", "diff.author_edit_cost"),
        ("diff.changed_files(base)", "diff.changed_files"),
        ("diff.changed_hunks(base, files)", "diff.changed_hunks"),
        ("diff.head_sha()", "diff.head_sha"),
        ("diff.resolve_base(base)", "diff.resolve_base"),
        ("discover.discover_fixable_rules(files)", "discover.discover_fixable_rules"),
        ("generate_coverage_xml()", "generate_coverage_xml"),
        ("load_config()", "load_config"),
        ("proc.wait(timeout=1)", "proc.wait"),
        ("proc.terminate()", "proc.terminate"),
        ("proc.kill()", "proc.kill"),
        ("runpy.run_module('pkg.mod')", "runpy.run_module"),
        ("simulate.simulate_format('sample.py')", "simulate.simulate_format"),
        ("simulate.simulate_rule('I001', ('sample.py',))", "simulate.simulate_rule"),
        ("uvx_tool('ruff')", "uvx_tool"),
        ("sys.exit(1)", "sys.exit"),
        ("write_crash(payload)", "write_crash"),
    ])
)
def test_side_effect_cautions_detect_runtime_boundary_calls(call: tuple[str, str]) -> None:
    expression, expected = call
    node = _function(f"def run_boundary(raw: str) -> str:\n    {expression}\n    return raw\n")

    assert any(expected in caution for caution in _side_effect_cautions(node))


@given(name=_IDENT)
def test_add_name_signal_records_first_matching_property_word(name: str) -> None:
    signals = _CandidateSignals()
    target = f"parse_{name}"

    _add_name_signal(signals, target)

    assert signals.score == 3
    assert signals.reasons == ["name suggests invariant (parse)"]


@given(
    name=_IDENT.filter(
        lambda value: all(
            word not in value
            for word in (
                "classify",
                "coerce",
                "compute",
                "detect",
                "filter",
                "format",
                "merge",
                "normalize",
                "parse",
                "pick",
                "read",
                "relpath",
                "resolve",
                "rewrite",
                "split",
                "validate",
            )
        )
    )
)
def test_add_name_signal_ignores_names_without_property_words(name: str) -> None:
    signals = _CandidateSignals()

    _add_name_signal(signals, name)

    assert signals.score == 0
    assert signals.reasons == []


@given(strategies=st.dictionaries(_IDENT, st.sampled_from(["st.text()", "tmp_path-derived Path"])))
def test_add_strategy_signals_scores_typed_inputs_and_path_caution(
    strategies: dict[str, str],
) -> None:
    signals = _CandidateSignals()

    _add_strategy_signals(signals, strategies)

    assert ("typed generated inputs" in signals.reasons) is bool(strategies)
    assert ("filesystem fixture required" in signals.cautions) is (
        "tmp_path-derived Path" in strategies.values()
    )


@given(method=_SIDE_EFFECT_METHOD)
def test_node_side_effect_cautions_classifies_call_nodes(method: str) -> None:
    call = ast.parse(f"path.{method}()").body[0]
    assert isinstance(call, ast.Expr)

    cautions = _node_side_effect_cautions(call.value)

    assert any(f"path.{method}" in caution for caution in cautions)


@given(kind=st.sampled_from(["raise", "global", "with"]))
def test_node_side_effect_cautions_classifies_non_call_boundaries(kind: str) -> None:
    source = {
        "raise": "def f() -> None:\n    raise RuntimeError('boom')\n",
        "global": "def f() -> None:\n    global configured\n",
        "with": "def f() -> None:\n    with resource:\n        pass\n",
    }[kind]
    node = _function(source).body[0]

    cautions = _node_side_effect_cautions(node)

    assert (
        cautions
        == {
            "raise": ["raises exceptions"],
            "global": ["mutates global state"],
            "with": ["context manager / resource boundary"],
        }[kind]
    )


@given(name=st.sampled_from(["capture", "path.write_text", "plain_call"]))
def test_known_side_effect_call_matches_short_or_full_names(name: str) -> None:
    short_name = name.rsplit(".", maxsplit=1)[-1]

    result = _known_side_effect_call(name, short_name)

    assert result is (name != "plain_call")


@given(name=_IDENT)
def test_known_side_effect_call_ignores_prefixed_unknown_names(name: str) -> None:
    short_name = f"safe_{name}"

    assert _known_side_effect_call(f"module.{short_name}", short_name) is False


@given(name=_IDENT)
def test_candidate_score_is_never_negative(name: str) -> None:
    node = _function(
        f"def {name}(path: Path) -> None:\n"
        f"    path.write_text('x')\n"
        f"    raise RuntimeError('boom')\n"
    )

    assert _candidate_from_function(node, "pkg/mod.py").score >= 0


@given(name=_IDENT)
def test_candidate_from_function_preserves_explicit_qualname(name: str) -> None:
    node = _function(
        f"def parse_{name}(raw: str) -> int:\n    if raw:\n        return len(raw)\n    return 0\n"
    )

    candidate = _candidate_from_function(
        node,
        "pkg/mod.py",
        qualname=f"Parser.parse_{name}",
    )

    assert candidate.name == f"parse_{name}"
    assert candidate.qualname == f"Parser.parse_{name}"
    assert candidate.path == "pkg/mod.py"


@given(names=st.lists(_IDENT, min_size=1, max_size=8, unique=True))
def test_candidates_from_tree_returns_generated_high_score_functions(names: list[str]) -> None:
    source = "\n\n".join(
        f"def parse_{name}(raw: str) -> int:\n    if raw:\n        return len(raw)\n    return 0\n"
        for name in names
    )
    tree = ast.parse(source)

    candidates = _candidates_from_tree(tree, "pkg/generated.py")

    by_name = {candidate.name: candidate for candidate in candidates}
    assert set(by_name) == {f"parse_{name}" for name in names}
    assert all(candidate.path == "pkg/generated.py" for candidate in candidates)
    assert all(candidate.strategies == {"raw": "st.text()"} for candidate in candidates)
    assert all(candidate.score >= 8 for candidate in candidates)


@given(name=_IDENT)
def test_candidates_from_tree_skips_nested_local_functions(name: str) -> None:
    source = (
        "def parse_outer(raw: str) -> int:\n"
        f"    def parse_{name}(inner: str) -> int:\n"
        "        if inner:\n"
        "            return len(inner)\n"
        "        return 0\n"
        "    if raw:\n"
        f"        return parse_{name}(raw)\n"
        "    return 0\n"
    )
    tree = ast.parse(source)

    candidates = _candidates_from_tree(tree, "pkg/generated.py")

    assert {candidate.name for candidate in candidates} == {"parse_outer"}
    assert [node.name for node in _candidate_function_nodes(tree)] == ["parse_outer"]
    assert [item.qualname for item in _candidate_function_items(tree)] == ["parse_outer"]


@given(method_name=_IDENT)
def test_candidates_from_tree_keeps_class_methods(method_name: str) -> None:
    source = (
        "class Parser:\n"
        f"    def parse_{method_name}(self, raw: str) -> int:\n"
        "        if raw:\n"
        "            return len(raw)\n"
        "        return 0\n"
    )
    tree = ast.parse(source)

    candidates = _candidates_from_tree(tree, "pkg/generated.py")

    assert {candidate.name for candidate in candidates} == {f"parse_{method_name}"}
    assert [node.name for node in _candidate_function_nodes(tree)] == [f"parse_{method_name}"]
    assert [item.qualname for item in _candidate_function_items(tree)] == [
        f"Parser.parse_{method_name}"
    ]


@given(rows=st.lists(_ANNOTATIONS, min_size=1, max_size=6, unique_by=lambda row: row[0]))
def test_strategies_for_args_extracts_supported_non_receiver_annotations(
    rows: list[tuple[str, str, str]],
) -> None:
    args = ", ".join(f"{name}: {annotation}" for name, annotation, _strategy in rows)
    source = f"def parse_args(self, cls, {args}) -> None:\n    return None\n"
    node = _function(source)

    strategies = _strategies_for_args(node)

    assert strategies == {name: strategy for name, _annotation, strategy in rows}
    assert "self" not in strategies
    assert "cls" not in strategies


def test_strategies_for_args_reads_positional_only_and_keyword_only_annotations() -> None:
    node = _function(
        "def parse_args(raw: str, /, *, count: int, enabled: bool = False) -> None:\n"
        "    return None\n"
    )

    assert _strategies_for_args(node) == {
        "raw": "st.text()",
        "count": "st.integers()",
        "enabled": "st.booleans()",
    }


@given(
    path=st.text(max_size=20),
    name=_IDENT,
    line=st.integers(min_value=1, max_value=10_000),
    score=st.integers(min_value=0, max_value=100),
    reasons=st.lists(st.text(max_size=20), max_size=10),
    cautions=st.lists(st.text(max_size=20), max_size=10),
    property_refs=st.integers(min_value=0, max_value=100),
)
def test_property_candidate_json_uses_plain_json_shapes(
    path: str,
    name: str,
    line: int,
    score: int,
    reasons: list[str],
    cautions: list[str],
    property_refs: int,
) -> None:
    candidate = PropertyCandidate(
        path=path,
        name=name,
        line=line,
        score=score,
        reasons=tuple(reasons),
        cautions=tuple(cautions),
        strategies={"raw": "st.text()"},
        property_refs=property_refs,
    )

    assert candidate.to_json() == {
        "path": path,
        "name": name,
        "qualname": name,
        "line": line,
        "score": score,
        "reasons": reasons,
        "cautions": cautions,
        "strategies": {"raw": "st.text()"},
        "property_refs": property_refs,
    }


@given(
    scope_ref=st.one_of(st.none(), _IDENT),
    include_referenced=st.booleans(),
    shown_count=st.integers(min_value=0, max_value=5),
)
def test_property_candidates_json_preserves_counts_and_scope(
    scope_ref: str | None, include_referenced: bool, shown_count: int
) -> None:
    all_candidates = [
        PropertyCandidate(
            path=f"pkg/mod_{index}.py",
            name=f"parse_{index}",
            line=index + 1,
            score=10,
            reasons=("typed generated inputs",),
            cautions=(),
            strategies={},
            property_refs=index % 2,
        )
        for index in range(shown_count + 2)
    ]
    candidates = (
        all_candidates
        if include_referenced
        else [candidate for candidate in all_candidates if candidate.property_refs == 0]
    )
    shown = candidates[:shown_count]
    state = _PropertyCandidatesState(
        cfg=InterlockConfig(
            project_root=Path(),
            src_dir=Path("pkg"),
            test_dir=Path("tests"),
            test_runner="pytest",
            test_invoker="python",
        ),
        scope_ref=scope_ref,
        include_referenced=include_referenced,
        all_candidates=all_candidates,
        candidates=candidates,
        shown=shown,
    )

    payload = _property_candidates_json(state)

    assert payload["scope"] == (f"changed vs {scope_ref}" if scope_ref else "all")
    assert state.json_scope_label == payload["scope"]
    assert payload["include_referenced"] is include_referenced
    assert payload["count"] == len(candidates)
    assert payload["total_count"] == state.total_count
    assert payload["referenced_count"] == state.referenced_count
    assert payload["unreferenced_count"] == state.unreferenced_count
    assert payload["shown"] == len(shown)
    assert payload["candidates"] == [candidate.to_json() for candidate in shown]
    assert "max_property_refs" not in payload
    assert "next_actions" not in payload


@given(candidate_count=st.integers(min_value=1, max_value=8))
def test_candidate_state_has_no_next_actions_when_candidates_are_available(
    candidate_count: int,
) -> None:
    candidates = [
        PropertyCandidate(
            path=f"pkg/mod_{index}.py",
            name=f"parse_{index}",
            line=index + 1,
            score=10,
            reasons=("typed generated inputs",),
            cautions=(),
            strategies={},
        )
        for index in range(candidate_count)
    ]
    state = _PropertyCandidatesState(
        cfg=InterlockConfig(
            project_root=Path(),
            src_dir=Path("pkg"),
            test_dir=Path("tests"),
            test_runner="pytest",
            test_invoker="python",
        ),
        scope_ref=None,
        include_referenced=True,
        all_candidates=candidates,
        candidates=candidates,
        shown=candidates,
        max_property_refs=0,
    )

    assert state.next_actions == ()
    assert "next_actions" not in _property_candidates_json(state)


@given(ref_counts=st.lists(st.integers(min_value=0, max_value=8), max_size=10))
def test_filter_by_max_property_refs_keeps_only_shallow_references(
    ref_counts: list[int],
) -> None:
    candidates = [
        PropertyCandidate(
            path=f"pkg/mod_{index}.py",
            name=f"parse_{index}",
            line=index + 1,
            score=10,
            reasons=("typed generated inputs",),
            cautions=(),
            strategies={},
            property_refs=refs,
        )
        for index, refs in enumerate(ref_counts)
    ]

    assert _filter_by_max_property_refs(candidates, None) == candidates
    for max_refs in range(3):
        assert _filter_by_max_property_refs(candidates, max_refs) == [
            candidate for candidate in candidates if candidate.property_refs <= max_refs
        ]


@given(
    ref_counts=st.lists(st.integers(min_value=0, max_value=8), max_size=10),
    low=st.integers(min_value=0, max_value=8),
    high=st.integers(min_value=0, max_value=8),
)
def test_filter_by_max_property_refs_is_monotonic(
    ref_counts: list[int],
    low: int,
    high: int,
) -> None:
    low, high = sorted((low, high))
    candidates = [
        PropertyCandidate(
            path=f"pkg/mod_{index}.py",
            name=f"parse_{index}",
            line=index + 1,
            score=10,
            reasons=("typed generated inputs",),
            cautions=(),
            strategies={},
            property_refs=refs,
        )
        for index, refs in enumerate(ref_counts)
    ]

    shallow = {candidate.name for candidate in _filter_by_max_property_refs(candidates, low)}
    broader = {candidate.name for candidate in _filter_by_max_property_refs(candidates, high)}

    assert shallow <= broader


@given(max_refs=st.integers(min_value=0, max_value=20), uncovered=st.booleans())
def test_max_property_refs_parses_uncovered_shortcut_and_value(
    max_refs: int,
    uncovered: bool,
) -> None:
    argv = ["interlocks", "property-candidates", f"--max-refs={max_refs}"]
    if uncovered:
        argv.append("--uncovered")
    old_argv = sys.argv
    try:
        sys.argv = argv
        assert _max_property_refs() == (0 if uncovered else max_refs)
    finally:
        sys.argv = old_argv


@given(argv_tail=st.lists(st.sampled_from(["--json", "--changed", "--limit=0"]), max_size=3))
def test_max_property_refs_defaults_to_none_without_ref_filters(argv_tail: list[str]) -> None:
    old_argv = sys.argv
    try:
        sys.argv = ["interlocks", "property-candidates", *argv_tail]
        assert _max_property_refs() is None
    finally:
        sys.argv = old_argv


@given(total=st.integers(min_value=1, max_value=20))
def test_uncovered_empty_message_reports_scope_and_all_referenced(total: int) -> None:
    candidates = [
        PropertyCandidate(
            path=f"pkg/mod_{index}.py",
            name=f"parse_{index}",
            line=index + 1,
            score=10,
            reasons=("typed generated inputs",),
            cautions=(),
            strategies={},
            property_refs=1,
        )
        for index in range(total)
    ]
    state = _PropertyCandidatesState(
        cfg=InterlockConfig(
            project_root=Path(),
            src_dir=Path("pkg"),
            test_dir=Path("tests"),
            test_runner="pytest",
            test_invoker="python",
        ),
        scope_ref="HEAD",
        include_referenced=False,
        all_candidates=candidates,
        candidates=[],
        shown=[],
        max_property_refs=0,
    )

    lines = _empty_candidate_lines(state)

    assert lines[0] == (
        f"  all {total} ranked candidate(s) in changed vs HEAD already have "
        "property-test references"
    )
    assert state.next_actions == (
        "Rerun without `--uncovered` to review referenced candidates.",
        "Add deeper invariants where property references are shallow.",
    )
    assert "rerun without `--uncovered`" in lines[1]


@given(
    total=st.integers(min_value=1, max_value=20), max_refs=st.integers(min_value=1, max_value=5)
)
def test_max_refs_empty_message_reports_shallow_reference_filter(
    total: int, max_refs: int
) -> None:
    candidates = [
        PropertyCandidate(
            path=f"pkg/mod_{index}.py",
            name=f"parse_{index}",
            line=index + 1,
            score=10,
            reasons=("typed generated inputs",),
            cautions=(),
            strategies={},
            property_refs=max_refs + 1,
        )
        for index in range(total)
    ]
    state = _PropertyCandidatesState(
        cfg=InterlockConfig(
            project_root=Path(),
            src_dir=Path("pkg"),
            test_dir=Path("tests"),
            test_runner="pytest",
            test_invoker="python",
        ),
        scope_ref="HEAD",
        include_referenced=True,
        all_candidates=candidates,
        candidates=[],
        shown=[],
        max_property_refs=max_refs,
    )

    lines = _empty_candidate_lines(state)
    payload = _property_candidates_json(state)

    assert payload["max_property_refs"] == max_refs
    assert lines[0] == (
        f"  all {total} ranked candidate(s) in changed vs HEAD have more than "
        f"{max_refs} property-test reference(s)"
    )
    assert "higher `--max-refs`" in lines[1]


def test_empty_candidate_state_reports_greenfield_next_actions() -> None:
    state = _PropertyCandidatesState(
        cfg=InterlockConfig(
            project_root=Path(),
            src_dir=Path("pkg"),
            test_dir=Path("tests"),
            test_runner="pytest",
            test_invoker="python",
        ),
        scope_ref=None,
        include_referenced=True,
        all_candidates=[],
        candidates=[],
        shown=[],
    )

    payload = _property_candidates_json(state)
    lines = _empty_candidate_lines(state)

    assert payload["next_actions"] == [
        "Extract or add typed, side-effect-light domain functions before property-test hardening.",
        "Run `interlocks init --properties` when domain invariants are ready.",
    ]
    assert "no source functions in all source" in lines[0]
    assert "extract or add typed" in lines[1]
    assert "init" in lines[2]


@given(
    shown_count=st.integers(min_value=1, max_value=5),
    total=st.integers(min_value=5, max_value=20),
)
def test_candidate_summary_line_reports_scope(shown_count: int, total: int) -> None:
    candidates = [
        PropertyCandidate(
            path=f"pkg/mod_{index}.py",
            name=f"parse_{index}",
            line=index + 1,
            score=10,
            reasons=("typed generated inputs",),
            cautions=(),
            strategies={},
            property_refs=index % 2,
        )
        for index in range(total)
    ]
    state = _PropertyCandidatesState(
        cfg=InterlockConfig(
            project_root=Path(),
            src_dir=Path("pkg"),
            test_dir=Path("tests"),
            test_runner="pytest",
            test_invoker="python",
        ),
        scope_ref="main",
        include_referenced=True,
        all_candidates=candidates,
        candidates=candidates,
        shown=candidates[:shown_count],
    )

    summary = _candidate_summary_line(state)

    assert f"showing {min(shown_count, total)} of {total}" in summary
    assert "in changed vs main" in summary


@given(
    message=st.sampled_from([
        "property-candidates: --limit must be an integer",
        "property-candidates: --limit must be >= 0",
    ])
)
def test_property_candidates_error_payload_keeps_limit_contract(message: str) -> None:
    payload = _property_candidates_error_payload(message)

    assert payload["command"] == "property-candidates"
    assert payload["error"] == message
    assert payload["usage"] == _property_candidates_usage()
    assert "--limit=N" in str(payload["usage"])
    assert payload["expected_limit"] == "integer >= 0"


@given(
    message=st.sampled_from([
        "property-candidates: --max-refs must be an integer",
        "property-candidates: --max-refs must be >= 0",
    ])
)
def test_property_candidates_error_payload_keeps_max_refs_contract(message: str) -> None:
    payload = _property_candidates_error_payload(message)

    assert payload["command"] == "property-candidates"
    assert payload["error"] == message
    assert payload["usage"] == _property_candidates_usage()
    assert "--max-refs=N" in str(payload["usage"])
    assert payload["expected_max_refs"] == "integer >= 0"
    assert "expected_limit" not in payload


@given(
    strategies=st.dictionaries(_IDENT, st.text(max_size=20), max_size=5),
    cautions=st.lists(st.text(max_size=20), max_size=5),
    property_refs=st.integers(min_value=0, max_value=100),
)
def test_property_candidate_detail_lines_match_optional_fields(
    strategies: dict[str, str], cautions: list[str], property_refs: int
) -> None:
    strategy_line = _strategy_line(strategies)
    caution_line = _caution_line(tuple(cautions))
    refs_line = _property_refs_line(property_refs)

    assert (strategy_line is not None) is bool(strategies)
    assert (caution_line is not None) is bool(cautions)
    assert (refs_line is not None) is bool(property_refs)
    if strategies:
        assert strategy_line is not None
        assert "strategies:" in strategy_line
    if cautions:
        assert caution_line is not None
        assert "caution:" in caution_line
    if property_refs:
        assert refs_line is not None
        assert str(property_refs) in refs_line


@given(cautions=st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=5))
def test_caution_line_caps_display_at_two_cautions(cautions: list[str]) -> None:
    assert _caution_line(tuple(cautions)) == "      caution: " + ", ".join(cautions[:2])


@given(property_refs=st.integers(min_value=1, max_value=100))
def test_property_refs_line_reports_positive_reference_count(property_refs: int) -> None:
    assert _property_refs_line(property_refs) == f"      properties: {property_refs} reference(s)"


@given(
    pairs=st.lists(st.tuples(_IDENT, _STRATEGY_TEXT), max_size=6, unique_by=lambda item: item[0])
)
def test_strategy_line_preserves_strategy_insertion_order(
    pairs: list[tuple[str, str]],
) -> None:
    strategies = dict(pairs)
    line = _strategy_line(strategies)

    if not pairs:
        assert line is None
    else:
        assert line == "      strategies: " + ", ".join(
            f"{name}={strategy}" for name, strategy in pairs
        )


def test_strategy_line_returns_none_for_empty_strategy_map() -> None:
    assert _strategy_line({}) is None


@given(
    pairs=st.lists(st.tuples(_IDENT, _STRATEGY_TEXT), max_size=6, unique_by=lambda item: item[0]),
    include_path_strategy=st.booleans(),
)
def test_add_strategy_signals_scores_typed_inputs_and_filesystem_caution_separately(
    pairs: list[tuple[str, str]],
    include_path_strategy: bool,
) -> None:
    strategies = dict(pairs)
    if include_path_strategy:
        strategies["path"] = "tmp_path-derived Path"
    signals = _CandidateSignals()

    _add_strategy_signals(signals, strategies)

    assert signals.score == ((3 if strategies else 0) - (2 if include_path_strategy else 0))
    assert ("typed generated inputs" in signals.reasons) is bool(strategies)
    assert ("filesystem fixture required" in signals.cautions) is include_path_strategy


def test_add_strategy_signals_leaves_empty_signal_state_unchanged() -> None:
    signals = _CandidateSignals()

    _add_strategy_signals(signals, {})

    assert signals.score == 0
    assert signals.reasons == []
    assert signals.cautions == []


@given(names=st.lists(_IDENT, min_size=1, max_size=10, unique=True))
def test_property_reference_counts_detect_module_resolved_generated_names(
    names: list[str],
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "generated.py").write_text(
            "\n".join(f"def {name}() -> None:\n    return None\n" for name in names),
            encoding="utf-8",
        )
        properties = root / "properties"
        properties.mkdir()
        imports = ", ".join(names)
        calls = "\n".join(f"    {name}()" for name in names)
        attrs = "\n".join(f"    generated.{name}()" for name in names)
        (properties / "test_generated_properties.py").write_text(
            f"from pkg import generated\nfrom pkg.generated import {imports}\n\n"
            f"def test_generated():\n{calls}\n{attrs}\n",
            encoding="utf-8",
        )
        cfg = InterlockConfig(
            project_root=root,
            src_dir=pkg,
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
            properties_dir=properties,
        )

        counts = _property_reference_counts(cfg)

    for name in names:
        assert counts.precise["pkg/generated.py", name] == 2


@given(
    name=_IDENT.filter(lambda value: value not in {"_call_generated", "test_generated"}),
    calls=st.integers(min_value=1, max_value=5),
)
def test_property_reference_counts_expand_local_property_helpers(
    name: str,
    calls: int,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "generated.py").write_text(
            f"def {name}() -> None:\n    return None\n",
            encoding="utf-8",
        )
        properties = root / "properties"
        properties.mkdir()
        helper_calls = "\n".join("    _call_generated()" for _ in range(calls))
        (properties / "test_generated_properties.py").write_text(
            f"from pkg.generated import {name}\n\n"
            "def _call_generated() -> None:\n"
            f"    {name}()\n\n"
            "def test_generated() -> None:\n"
            f"{helper_calls}\n",
            encoding="utf-8",
        )
        cfg = InterlockConfig(
            project_root=root,
            src_dir=pkg,
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
            properties_dir=properties,
        )

        counts = _property_reference_counts(cfg)

    assert counts.precise["pkg/generated.py", name] == calls


@given(name=_IDENT.filter(lambda value: value not in {"_helper", "test_generated"}))
def test_local_helper_reference_map_ignores_private_helpers_without_references(name: str) -> None:
    tree = ast.parse(f"def _helper() -> None:\n    {name} = 1\n")
    assert isinstance(tree, ast.Module)
    cfg = InterlockConfig(
        project_root=Path(),
        src_dir=Path("pkg"),
        test_dir=Path("tests"),
        test_runner="pytest",
        test_invoker="python",
    )

    assert _local_helper_reference_map(cfg, _ReferenceAliases({}, {}, {}), tree, frozenset()) == {}


@given(name=_IDENT.filter(lambda value: value not in {"_call_generated", "call_generated"}))
def test_local_helper_reference_map_tracks_private_helpers_only(name: str) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "generated.py").write_text(
            f"def {name}() -> None:\n    return None\n",
            encoding="utf-8",
        )
        source = (
            f"from pkg.generated import {name}\n\n"
            "def _call_generated() -> None:\n"
            f"    {name}()\n\n"
            "def call_generated() -> None:\n"
            f"    {name}()\n"
        )
        tree = ast.parse(source)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=pkg,
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
            properties_dir=root / "properties",
        )
        module_aliases = _reference_aliases(cfg, tree)

        helper_refs = _local_helper_reference_map(cfg, module_aliases, tree, frozenset())

    assert helper_refs == {"_call_generated": (("pkg/generated.py", name),)}


@given(targets=st.lists(_IDENT, max_size=5, unique=True), value_name=_IDENT)
def test_record_instance_aliases_ignores_non_constructor_values(
    targets: list[str],
    value_name: str,
) -> None:
    cfg = InterlockConfig(
        project_root=Path(),
        src_dir=Path(),
        test_dir=Path("tests"),
        test_runner="pytest",
        test_invoker="python",
    )
    aliases = _ReferenceAliases({}, {}, {})
    target_nodes = tuple(ast.Name(name, ast.Store()) for name in targets)

    _record_instance_aliases(cfg, aliases, target_nodes, ast.Name(value_name, ast.Load()))

    assert aliases.instances == {}


@given(target=_IDENT)
def test_record_instance_aliases_records_constructor_calls(target: str) -> None:
    cfg = InterlockConfig(
        project_root=Path(),
        src_dir=Path(),
        test_dir=Path("tests"),
        test_runner="pytest",
        test_invoker="python",
    )
    aliases = _ReferenceAliases({}, {"Parser": ("pkg/generated.py", "Parser")}, {})
    assignment = ast.parse(f"{target} = Parser()").body[0]
    assert isinstance(assignment, ast.Assign)

    _record_instance_aliases(cfg, aliases, assignment.targets, assignment.value)

    assert aliases.instances == {target: ("pkg/generated.py", "Parser")}


@given(alias=_IDENT)
def test_record_import_aliases_ignores_unknown_modules(alias: str) -> None:
    cfg = InterlockConfig(
        project_root=Path(),
        src_dir=Path(),
        test_dir=Path("tests"),
        test_runner="pytest",
        test_invoker="python",
    )
    node = ast.parse(f"import missing.generated as {alias}").body[0]
    assert isinstance(node, ast.Import)
    modules: dict[str, str] = {}

    _record_import_aliases(cfg, node, modules)

    assert modules == {}


@given(alias=_IDENT)
def test_record_import_aliases_removes_ambiguous_local_aliases(alias: str) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "one.py").write_text("", encoding="utf-8")
        (pkg / "two.py").write_text("", encoding="utf-8")
        cfg = InterlockConfig(
            project_root=root,
            src_dir=pkg,
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
        )
        tree = ast.parse(f"import pkg.one as {alias}\nimport pkg.two as {alias}\n")
        modules: dict[str, str] = {}
        ambiguous: set[str] = set()

        for node in tree.body:
            assert isinstance(node, ast.Import)
            _record_import_aliases(cfg, node, modules, ambiguous)

    assert modules == {}
    assert ambiguous == {alias}


@given(parts=st.lists(_IDENT, max_size=5).map(tuple))
def test_reference_for_module_parts_returns_none_without_matching_module(
    parts: tuple[str, ...],
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "pkg",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
        )

        assert _reference_for_module_parts(cfg, parts) is None


@given(name=_IDENT, member=_IDENT)
def test_reference_for_module_parts_uses_longest_existing_module_prefix(
    name: str,
    member: str,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        package = root / "pkg"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "generated.py").write_text("", encoding="utf-8")
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "pkg",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
        )

        assert _reference_for_module_parts(cfg, ("pkg", "generated", name, member)) == (
            "pkg/generated.py",
            f"{name}.{member}",
        )


@given(alias=_IDENT)
def test_scope_reference_aliases_let_local_imports_override_module_aliases(alias: str) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "one.py").write_text("def parse() -> None:\n    return None\n", encoding="utf-8")
        (pkg / "two.py").write_text("def parse() -> None:\n    return None\n", encoding="utf-8")
        cfg = InterlockConfig(
            project_root=root,
            src_dir=pkg,
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
        )
        scope = _function(f"def test_scope() -> None:\n    from pkg.two import parse as {alias}\n")
        module_aliases = _ReferenceAliases({}, {alias: ("pkg/one.py", "parse")}, {})

        aliases = _scope_reference_aliases(cfg, module_aliases, scope)

    assert aliases.objects[alias] == ("pkg/two.py", "parse")
    assert module_aliases.objects[alias] == ("pkg/one.py", "parse")


@given(name=_IDENT, method=_IDENT)
def test_reference_resolution_distinguishes_module_and_class_symbols(
    name: str,
    method: str,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "generated.py").write_text(
            f"def {name}() -> None:\n    return None\n\n"
            f"class Parser:\n    def {method}(self) -> None:\n        return None\n",
            encoding="utf-8",
        )
        cfg = InterlockConfig(
            project_root=root,
            src_dir=pkg,
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
            properties_dir=root / "properties",
        )
        module_import = ast.parse("import pkg.generated as generated").body[0]
        object_import = ast.parse(f"from pkg.generated import {name}, Parser").body[0]
        assert isinstance(module_import, ast.Import)
        assert isinstance(object_import, ast.ImportFrom)
        aliases = _ReferenceAliases({}, {}, {})

        _record_import_aliases(cfg, module_import, aliases.modules)
        _record_import_from_aliases(cfg, object_import, aliases)
        import_source = (
            f"import pkg.generated as generated\nfrom pkg.generated import {name}, Parser\n"
            "parser = Parser()\n"
            "\n"
            "def test_local_reference() -> None:\n"
            "    local = Parser()\n"
            f"    local.{method}()\n"
        )
        import_tree = ast.parse(import_source)
        aliases = _reference_aliases(
            cfg,
            import_tree,
        )
        function_node = ast.parse(f"{name}()").body[0]
        module_node = ast.parse(f"generated.{name}()").body[0]
        method_node = ast.parse(f"Parser.{method}(None)").body[0]
        instance_node = ast.parse(f"parser.{method}()").body[0]
        attribute_node = ast.parse(f"parser.{method}").body[0]
        extra_assignment = ast.parse("other = Parser()").body[0]
        assert isinstance(function_node, ast.Expr)
        assert isinstance(module_node, ast.Expr)
        assert isinstance(method_node, ast.Expr)
        assert isinstance(instance_node, ast.Expr)
        assert isinstance(attribute_node, ast.Expr)
        assert isinstance(extra_assignment, ast.Assign)
        assert isinstance(function_node.value, ast.Call)
        assert isinstance(module_node.value, ast.Call)
        assert isinstance(method_node.value, ast.Call)
        assert isinstance(instance_node.value, ast.Call)
        assert isinstance(attribute_node.value, ast.Attribute)

        _record_instance_aliases(cfg, aliases, extra_assignment.targets, extra_assignment.value)
        direct = _resolved_reference(cfg, aliases, function_node.value.func)
        module_ref = _resolved_reference(cfg, aliases, module_node.value.func)
        method_ref = _resolved_reference(cfg, aliases, method_node.value.func)
        instance_ref = _resolved_reference(cfg, aliases, instance_node.value.func)
        attribute_refs = _resolved_references(
            cfg,
            aliases,
            attribute_node,
            frozenset({("pkg/generated.py", f"Parser.{method}")}),
        )
        attribute_ref = _child_reference(
            cfg,
            aliases,
            attribute_node.value,
            frozenset(),
            frozenset({("pkg/generated.py", f"Parser.{method}")}),
        )
        call_attribute_ref = _child_reference(
            cfg,
            aliases,
            instance_node.value.func,
            frozenset({id(instance_node.value.func)}),
            frozenset({("pkg/generated.py", f"Parser.{method}")}),
        )
        non_property_attribute_refs = _resolved_references(cfg, aliases, attribute_node)
        scope = import_tree.body[-1]
        assert isinstance(scope, ast.FunctionDef)
        scope_aliases = _scope_reference_aliases(cfg, aliases, scope)
        scoped_refs = _resolved_references(cfg, scope_aliases, scope)
        tree_refs = _property_references_from_tree(cfg, import_tree)

        assert aliases.modules == {"generated": "pkg.generated"}
        assert aliases.objects == {
            name: ("pkg/generated.py", name),
            "Parser": ("pkg/generated.py", "Parser"),
        }
        assert aliases.instances == {
            "parser": ("pkg/generated.py", "Parser"),
            "other": ("pkg/generated.py", "Parser"),
        }
        assert _looks_like_class_symbol("Parser")
        assert _looks_like_class_symbol("_Parser")
        assert not _looks_like_class_symbol(name.lower())
        assert _module_relpath(cfg, "pkg.generated") == "pkg/generated.py"
        assert _reference_for_module_parts(cfg, ("pkg", "generated", name)) == (
            "pkg/generated.py",
            name,
        )
        assert direct == ("pkg/generated.py", name)
        assert module_ref == ("pkg/generated.py", name)
        assert method_ref == ("pkg/generated.py", f"Parser.{method}")
        assert instance_ref == ("pkg/generated.py", f"Parser.{method}")
        assert attribute_refs == [("pkg/generated.py", f"Parser.{method}")]
        assert attribute_ref == ("pkg/generated.py", f"Parser.{method}")
        assert call_attribute_ref is None
        assert non_property_attribute_refs == []
        assert ("pkg/generated.py", f"Parser.{method}") in scoped_refs
        assert scoped_refs.count(("pkg/generated.py", f"Parser.{method}")) == 1
        assert ("pkg/generated.py", f"Parser.{method}") in tree_refs


@given(name=_IDENT)
def test_property_references_from_tree_counts_top_level_resolved_calls(name: str) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "generated.py").write_text(
            f"def {name}() -> None:\n    return None\n",
            encoding="utf-8",
        )
        cfg = InterlockConfig(
            project_root=root,
            src_dir=pkg,
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
        )
        tree = ast.parse(f"from pkg.generated import {name}\n{name}()\n")

        refs = _property_references_from_tree(cfg, tree)

    assert refs == [("pkg/generated.py", name)]


@given(name=_IDENT)
def test_property_attribute_symbols_track_property_like_decorators(name: str) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "generated.py").write_text(
            "from functools import cached_property\n\n"
            "class Parser:\n"
            "    @property\n"
            f"    def {name}(self) -> int:\n"
            "        return 1\n\n"
            "    @cached_property\n"
            f"    def cached_{name}(self) -> int:\n"
            "        return 2\n\n"
            f"    def plain_{name}(self) -> int:\n"
            "        return 3\n",
            encoding="utf-8",
        )
        cfg = InterlockConfig(
            project_root=root,
            src_dir=pkg,
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
        )

        symbols = _property_attribute_symbols(cfg)
        tree_symbols = _property_attribute_symbols_from_tree(
            ast.parse((pkg / "generated.py").read_text(encoding="utf-8")),
            "pkg/generated.py",
        )

    assert symbols == frozenset({
        ("pkg/generated.py", f"Parser.{name}"),
        ("pkg/generated.py", f"Parser.cached_{name}"),
    })
    assert tree_symbols == set(symbols)


@given(relpath=st.text(max_size=40))
def test_property_attribute_symbols_ignore_non_module_trees(relpath: str) -> None:
    assert _property_attribute_symbols_from_tree(ast.Expression(ast.Constant(1)), relpath) == set()


@given(name=_IDENT)
def test_property_attribute_symbols_ignore_plain_methods(name: str) -> None:
    tree = ast.parse(f"class Parser:\n    def {name}(self) -> int:\n        return 1\n")

    assert _property_attribute_symbols_from_tree(tree, "pkg/generated.py") == set()


@given(
    decorator=st.sampled_from([
        "property",
        "property()",
        "cached_property",
        "cached_property()",
        "functools.cached_property",
        "functools.cached_property()",
        "pytest.fixture",
        "staticmethod",
    ])
)
def test_has_property_decorator_matches_property_like_names(decorator: str) -> None:
    node = _function(f"@{decorator}\ndef value(self) -> int:\n    return 1\n")
    expected = decorator.removesuffix("()").rsplit(".", maxsplit=1)[-1] in {
        "property",
        "cached_property",
    }

    assert _has_property_decorator(node) is expected


@given(
    decorator=_IDENT.filter(
        lambda value: value not in {"property", "cached_property", "functools"}
    )
)
def test_has_property_decorator_ignores_unrelated_decorator_names(decorator: str) -> None:
    node = _function(f"@{decorator}\ndef value(self) -> int:\n    return 1\n")

    assert _has_property_decorator(node) is False


@given(
    local=_IDENT,
    first=_IDENT,
    second=_IDENT,
)
def test_record_unique_alias_drops_conflicting_targets_when_ambiguity_is_tracked(
    local: str,
    first: str,
    second: str,
) -> None:
    aliases: dict[str, str] = {}
    ambiguous: set[str] = set()

    _record_unique_alias(aliases, local, first, ambiguous)
    _record_unique_alias(aliases, local, second, ambiguous)
    _record_unique_alias(aliases, local, first, ambiguous)

    if first == second:
        assert aliases == {local: first}
        assert ambiguous == set()
    else:
        assert aliases == {}
        assert ambiguous == {local}


@given(names=st.lists(_IDENT, min_size=1, max_size=8, unique_by=str.lower))
def test_iter_source_files_skips_init_and_pycache_sources(names: list[str]) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        src = root / "pkg"
        src.mkdir()
        (src / "__init__.py").write_text("", encoding="utf-8")
        (src / "__pycache__").mkdir()
        (src / "__pycache__" / "cached.py").write_text("", encoding="utf-8")
        expected = []
        for name in names:
            path = src / f"{name}.py"
            path.write_text("x = 1\n", encoding="utf-8")
            expected.append(path)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=src,
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
        )

        sources = _iter_source_files(cfg)

    assert sources == sorted(expected)


@given(name=_IDENT)
def test_iter_source_files_accepts_single_python_file_source(name: str) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        source = root / f"{name}.py"
        source.write_text("x = 1\n", encoding="utf-8")
        cfg = InterlockConfig(
            project_root=root,
            src_dir=source,
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
        )

        sources = _iter_source_files(cfg)

    assert sources == [source]


@given(module=st.text(max_size=80))
def test_module_relpath_rejects_invalid_or_missing_modules(module: str) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        src = root / "pkg"
        src.mkdir()
        cfg = InterlockConfig(
            project_root=root,
            src_dir=src,
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
        )

        result = _module_relpath(cfg, module)

    assert result is None


@given(parts=st.lists(_IDENT, min_size=1, max_size=4, unique=True))
def test_module_relpath_resolves_valid_project_modules(parts: list[str]) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        src = root / "src"
        module_path = root.joinpath(*parts).with_suffix(".py")
        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.write_text("x = 1\n", encoding="utf-8")
        cfg = InterlockConfig(
            project_root=root,
            src_dir=src,
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
        )

        result = _module_relpath(cfg, ".".join(parts))

    assert result == "/".join((*parts[:-1], f"{parts[-1]}.py"))


@given(names=st.lists(_IDENT, min_size=1, max_size=8, unique_by=str.lower))
def test_property_candidates_ranks_generated_parse_functions(names: list[str]) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        src = root / "pkg"
        src.mkdir()
        source = "\n\n".join(
            f"def parse_{name}(raw: str) -> int:\n"
            "    if raw:\n"
            "        return len(raw)\n"
            "    return 0\n"
            for name in names
        )
        (src / "generated.py").write_text(source, encoding="utf-8")
        properties = root / "properties"
        cfg = InterlockConfig(
            project_root=root,
            src_dir=src,
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
            properties_dir=properties,
        )

        candidates = property_candidates(cfg)

    assert {candidate.name for candidate in candidates} == {f"parse_{name}" for name in names}
    assert all(candidate.property_refs == 0 for candidate in candidates)


@given(names=st.lists(_IDENT, min_size=2, max_size=8, unique_by=str.lower))
def test_property_candidates_can_filter_referenced_candidates(names: list[str]) -> None:
    referenced = set(names[::2])
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        source = "\n\n".join(
            f"def parse_{name}(raw: str) -> int:\n"
            "    if raw:\n"
            "        return len(raw)\n"
            "    return 0\n"
            for name in names
        )
        (pkg / "generated.py").write_text(source, encoding="utf-8")
        properties = root / "properties"
        properties.mkdir()
        imports = ", ".join(f"parse_{name}" for name in sorted(referenced))
        calls = "\n".join(f"    parse_{name}('x')" for name in sorted(referenced))
        (properties / "test_generated_properties.py").write_text(
            f"from pkg.generated import {imports}\n\ndef test_generated() -> None:\n{calls}\n",
            encoding="utf-8",
        )
        cfg = InterlockConfig(
            project_root=root,
            src_dir=pkg,
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
            properties_dir=properties,
        )

        all_candidates = property_candidates(cfg)
        uncovered = property_candidates(cfg, include_referenced=False)

    assert {candidate.name for candidate in all_candidates} == {f"parse_{name}" for name in names}
    assert {candidate.name for candidate in uncovered} == {
        f"parse_{name}" for name in names if name not in referenced
    }
