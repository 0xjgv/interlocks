"""Property tests for property-candidate ranking helpers."""

from __future__ import annotations

import ast
import keyword
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
    _candidates_from_tree,
    _CandidateSignals,
    _caution_line,
    _iter_source_files,
    _known_side_effect_call,
    _looks_like_class_symbol,
    _module_relpath,
    _node_side_effect_cautions,
    _property_candidates_error_payload,
    _property_candidates_json,
    _property_candidates_usage,
    _property_reference_counts,
    _property_references_from_tree,
    _property_refs_line,
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


@given(name=st.sampled_from(["capture", "path.write_text", "plain_call"]))
def test_known_side_effect_call_matches_short_or_full_names(name: str) -> None:
    short_name = name.rsplit(".", maxsplit=1)[-1]

    result = _known_side_effect_call(name, short_name)

    assert result is (name != "plain_call")


@given(name=_IDENT)
def test_candidate_score_is_never_negative(name: str) -> None:
    node = _function(
        f"def {name}(path: Path) -> None:\n"
        f"    path.write_text('x')\n"
        f"    raise RuntimeError('boom')\n"
    )

    assert _candidate_from_function(node, "pkg/mod.py").score >= 0


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
        for index in range(shown_count + 2)
    ]
    shown = candidates[:shown_count]

    payload = _property_candidates_json(
        scope_ref=scope_ref,
        include_referenced=include_referenced,
        candidates=candidates,
        shown=shown,
    )

    assert payload["scope"] == (f"changed vs {scope_ref}" if scope_ref else "all")
    assert payload["include_referenced"] is include_referenced
    assert payload["count"] == len(candidates)
    assert payload["shown"] == shown_count
    assert payload["candidates"] == [candidate.to_json() for candidate in shown]


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
        extra_assignment = ast.parse("other = Parser()").body[0]
        assert isinstance(function_node, ast.Expr)
        assert isinstance(module_node, ast.Expr)
        assert isinstance(method_node, ast.Expr)
        assert isinstance(instance_node, ast.Expr)
        assert isinstance(extra_assignment, ast.Assign)
        assert isinstance(function_node.value, ast.Call)
        assert isinstance(module_node.value, ast.Call)
        assert isinstance(method_node.value, ast.Call)
        assert isinstance(instance_node.value, ast.Call)

        _record_instance_aliases(cfg, aliases, extra_assignment.targets, extra_assignment.value)
        direct = _resolved_reference(cfg, aliases, function_node.value.func)
        module_ref = _resolved_reference(cfg, aliases, module_node.value.func)
        method_ref = _resolved_reference(cfg, aliases, method_node.value.func)
        instance_ref = _resolved_reference(cfg, aliases, instance_node.value.func)
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
        assert ("pkg/generated.py", f"Parser.{method}") in scoped_refs
        assert ("pkg/generated.py", f"Parser.{method}") in tree_refs


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
