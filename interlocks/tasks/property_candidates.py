"""Static property-test candidate ranking."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn, TypeVar

from interlocks import ui
from interlocks.config import InterlockConfig, load_config
from interlocks.git import changed_py_files_vs
from interlocks.runner import arg_flag_value, arg_value, fail_skip

_DEFAULT_CANDIDATE_LIMIT = 20
_CANDIDATE_MIN_SCORE = 8
_AliasTarget = TypeVar("_AliasTarget")

_PROPERTY_NAME_WORDS = (
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
_SIDE_EFFECT_CALLS = frozenset({
    "BrowserTransport.submit",
    "_restore",
    "_skip_crap_advisory",
    "_apply_candidate_batch",
    "_snapshot",
    "_verify_candidate_batch",
    "apply_format",
    "apply_rule",
    "build_payload",
    "capture",
    "classify_acceptance_with_details",
    "coverage_line_rate",
    "diff.author_edit_cost",
    "diff.changed_files",
    "diff.changed_hunks",
    "diff.head_sha",
    "diff.resolve_base",
    "discover.discover_fixable_rules",
    "discover_fixable_rules",
    "evidence_is_fresh",
    "exit",
    "fail_skip",
    "generate_coverage_xml",
    "input",
    "load_config",
    "ok",
    "open",
    "print",
    "prompt_for_report",
    "record_seen",
    "run",
    "run_module",
    "run_tasks",
    "runpy.run_module",
    "_resolve_changed_globs",
    "_skip_mutation_low_coverage",
    "_skip_mutation_no_changed_src",
    "_skip_mutation_no_coverage",
    "task_acceptance_with_attribution",
    "simulate.simulate_format",
    "simulate.simulate_rule",
    "simulate_format",
    "simulate_rule",
    "uvx_tool",
    "verify.apply_many_candidates_with_verify",
    "verify.apply_many_with_verify",
    "warn_skip",
    "write_crash",
    "ui.banner",
    "ui.command_banner",
    "ui.command_footer",
    "ui.gate_row",
    "ui.group_header",
    "ui.kv_block",
    "ui.message_list",
    "ui.print_next_actions",
    "ui.print_json",
    "ui.row",
    "ui.section",
    "ui.stage_footer",
})
_SIDE_EFFECT_METHODS = frozenset({
    "chmod",
    "close",
    "mkdir",
    "open",
    "replace",
    "kill",
    "read_bytes",
    "read_text",
    "rmdir",
    "symlink_to",
    "terminate",
    "touch",
    "wait",
    "unlink",
    "write",
    "write_bytes",
    "write_text",
})
_BRANCH_NODES = (
    ast.BoolOp,
    ast.ExceptHandler,
    ast.For,
    ast.If,
    ast.IfExp,
    ast.Match,
    ast.Try,
    ast.While,
    ast.comprehension,
)
_EXACT_STRATEGIES = {
    "int": "st.integers()",
    "builtins.int": "st.integers()",
    "float": "st.floats(allow_nan=False)",
    "builtins.float": "st.floats(allow_nan=False)",
    "str": "st.text()",
    "builtins.str": "st.text()",
    "bool": "st.booleans()",
    "builtins.bool": "st.booleans()",
}


@dataclass(frozen=True, slots=True)
class PropertyCandidate:
    """One function that looks suitable for property-test hardening."""

    path: str
    name: str
    line: int
    score: int
    reasons: tuple[str, ...]
    cautions: tuple[str, ...]
    strategies: dict[str, str]
    qualname: str | None = None
    property_refs: int = 0

    def to_json(self) -> dict[str, object]:
        return {
            "path": self.path,
            "name": self.name,
            "qualname": self.qualname or self.name,
            "line": self.line,
            "score": self.score,
            "reasons": list(self.reasons),
            "cautions": list(self.cautions),
            "strategies": self.strategies,
            "property_refs": self.property_refs,
        }


@dataclass(frozen=True, slots=True)
class _PropertyReferenceCounts:
    precise: dict[tuple[str, str], int]

    def for_candidate(self, candidate: PropertyCandidate) -> int:
        return self.precise.get((candidate.path, candidate.qualname or candidate.name), 0)


@dataclass(slots=True)
class _CandidateSignals:
    score: int = 0
    reasons: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _PropertyCandidatesState:
    cfg: InterlockConfig
    scope_ref: str | None
    include_referenced: bool
    all_candidates: list[PropertyCandidate]
    candidates: list[PropertyCandidate]
    shown: list[PropertyCandidate]

    @property
    def total_count(self) -> int:
        return len(self.all_candidates)

    @property
    def scope_label(self) -> str:
        return f"changed vs {self.scope_ref}" if self.scope_ref else "all source"

    @property
    def json_scope_label(self) -> str:
        return f"changed vs {self.scope_ref}" if self.scope_ref else "all"

    @property
    def referenced_count(self) -> int:
        return sum(1 for candidate in self.all_candidates if candidate.property_refs)

    @property
    def unreferenced_count(self) -> int:
        return self.total_count - self.referenced_count

    @property
    def next_actions(self) -> tuple[str, ...]:
        if self.candidates:
            return ()
        if self.total_count and not self.include_referenced:
            return (
                "Rerun without `--uncovered` to review referenced candidates.",
                "Add deeper invariants where property references are shallow.",
            )
        if not self.total_count:
            return (
                "Extract or add typed, side-effect-light domain functions before "
                "property-test hardening.",
                "Run `interlocks init-properties` when domain invariants are ready.",
            )
        return ()

    def to_json(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "command": "property-candidates",
            "scope": self.json_scope_label,
            "include_referenced": self.include_referenced,
            "count": len(self.candidates),
            "total_count": self.total_count,
            "referenced_count": self.referenced_count,
            "unreferenced_count": self.unreferenced_count,
            "shown": len(self.shown),
            "candidates": [candidate.to_json() for candidate in self.shown],
        }
        if self.next_actions:
            payload["next_actions"] = list(self.next_actions)
        return payload


def property_candidates(
    cfg: InterlockConfig, *, changed: set[str] | None = None, include_referenced: bool = True
) -> list[PropertyCandidate]:
    """Rank source functions that look useful for generated-input tests."""
    candidates: list[PropertyCandidate] = []
    for source in _iter_source_files(cfg):
        rel = cfg.relpath(source)
        if changed is not None and rel not in changed:
            continue
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=rel)
        except (OSError, SyntaxError):
            continue
        candidates.extend(_candidates_from_tree(tree, rel))
    refs = _property_reference_counts(cfg)
    candidates = [
        _with_property_refs(candidate, refs.for_candidate(candidate)) for candidate in candidates
    ]
    if not include_referenced:
        candidates = [candidate for candidate in candidates if candidate.property_refs == 0]
    return sorted(candidates, key=lambda c: (-c.score, c.path, c.line, c.name))


def cmd_property_candidates() -> None:
    state = _property_candidates_command_state()
    if ui.is_json():
        ui.print_json(_property_candidates_json(state))
        return
    _render_property_candidates(state)


def _property_candidates_command_state() -> _PropertyCandidatesState:
    cfg = load_config()
    limit = _candidate_limit()
    scope_ref = arg_flag_value("--changed", cfg.changed_ref)
    changed = changed_py_files_vs(scope_ref) if scope_ref else None
    include_referenced = arg_flag_value("--uncovered", "1") is None
    all_candidates = property_candidates(cfg, changed=changed, include_referenced=True)
    candidates = (
        all_candidates
        if include_referenced
        else [candidate for candidate in all_candidates if candidate.property_refs == 0]
    )
    shown = candidates[:limit] if limit else candidates
    return _PropertyCandidatesState(
        cfg=cfg,
        scope_ref=scope_ref,
        include_referenced=include_referenced,
        all_candidates=all_candidates,
        candidates=candidates,
        shown=shown,
    )


def _property_candidates_json(state: _PropertyCandidatesState) -> dict[str, object]:
    return state.to_json()


def _render_property_candidates(state: _PropertyCandidatesState) -> None:
    ui.command_banner("property-candidates", state.cfg)
    ui.section("Property Candidates")
    if not state.shown:
        for line in _empty_candidate_lines(state):
            print(line)
        return
    print(_candidate_summary_line(state))
    for candidate in state.shown:
        for line in _candidate_display_lines(candidate):
            print(line)


def _candidate_summary_line(state: _PropertyCandidatesState) -> str:
    if state.include_referenced:
        return (
            f"  showing {len(state.shown)} of {len(state.candidates)} ranked candidate(s) "
            f"in {state.scope_label}"
        )
    return (
        f"  showing {len(state.shown)} of {len(state.candidates)} unreferenced candidate(s) "
        f"in {state.scope_label} ({state.referenced_count} referenced)"
    )


def _empty_candidate_lines(state: _PropertyCandidatesState) -> tuple[str, ...]:
    next_lines = tuple(ui.next_action_line(action, indent="  ") for action in state.next_actions)
    if not state.total_count:
        return (
            f"  no source functions in {state.scope_label} look like strong "
            "property-test candidates",
            *next_lines,
        )
    if not state.include_referenced:
        return (
            f"  all {state.total_count} ranked candidate(s) in {state.scope_label} already "
            "have property-test references",
            *next_lines,
        )
    return ("  no source functions look like strong property-test candidates",)


def _candidate_display_lines(candidate: PropertyCandidate) -> list[str]:
    location = f"{candidate.path}:{candidate.line}"
    reasons = ", ".join(candidate.reasons[:3])
    display_name = candidate.qualname or candidate.name
    first = f"  {candidate.score:2d}  {location:<42} {display_name} — {reasons}"
    return [first, *_candidate_detail_lines(candidate)]


def _candidate_detail_lines(candidate: PropertyCandidate) -> list[str]:
    return [
        line
        for line in (
            _strategy_line(candidate.strategies),
            _caution_line(candidate.cautions),
            _property_refs_line(candidate.property_refs),
        )
        if line is not None
    ]


def _strategy_line(strategies: dict[str, str]) -> str | None:
    if not strategies:
        return None
    strategy_text = ", ".join(f"{name}={strategy}" for name, strategy in strategies.items())
    return f"      strategies: {strategy_text}"


def _caution_line(cautions: tuple[str, ...]) -> str | None:
    if not cautions:
        return None
    return f"      caution: {', '.join(cautions[:2])}"


def _property_refs_line(property_refs: int) -> str | None:
    if not property_refs:
        return None
    return f"      properties: {property_refs} reference(s)"


def _iter_source_files(cfg: InterlockConfig) -> list[Path]:
    root = cfg.src_dir
    if root.is_file() and root.suffix == ".py":
        return [root]
    if not root.is_dir():
        return []
    return sorted(
        path
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts and path.name != "__init__.py"
    )


def _candidates_from_tree(tree: ast.AST, relpath: str) -> list[PropertyCandidate]:
    out: list[PropertyCandidate] = []
    for item in _candidate_function_items(tree):
        candidate = _candidate_from_function(item.node, relpath, qualname=item.qualname)
        if candidate.score >= _CANDIDATE_MIN_SCORE:
            out.append(candidate)
    return out


@dataclass(frozen=True, slots=True)
class _CandidateFunction:
    node: ast.FunctionDef | ast.AsyncFunctionDef
    qualname: str


def _candidate_function_items(tree: ast.AST) -> list[_CandidateFunction]:
    """Return top-level functions and class methods with stable property symbols."""
    out: list[_CandidateFunction] = []
    if not isinstance(tree, ast.Module):
        return out
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            out.append(_CandidateFunction(node, node.name))
        elif isinstance(node, ast.ClassDef):
            out.extend(
                _CandidateFunction(child, f"{node.name}.{child.name}")
                for child in node.body
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
            )
    return out


def _candidate_function_nodes(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Return top-level functions and class methods, excluding local nested functions."""
    return [item.node for item in _candidate_function_items(tree)]


def _with_property_refs(candidate: PropertyCandidate, refs: int) -> PropertyCandidate:
    return PropertyCandidate(
        path=candidate.path,
        name=candidate.name,
        line=candidate.line,
        score=candidate.score,
        reasons=candidate.reasons,
        cautions=candidate.cautions,
        strategies=candidate.strategies,
        qualname=candidate.qualname,
        property_refs=refs,
    )


def _property_reference_counts(cfg: InterlockConfig) -> _PropertyReferenceCounts:
    root = cfg.properties_dir
    if root is None or not root.is_dir():
        return _PropertyReferenceCounts({})
    property_attributes = _property_attribute_symbols(cfg)
    counts: dict[tuple[str, str], int] = {}
    for source in sorted(root.rglob("*.py")):
        if "__pycache__" in source.parts:
            continue
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        except (OSError, SyntaxError):
            continue
        for ref in _property_references_from_tree(cfg, tree, property_attributes):
            counts[ref] = counts.get(ref, 0) + 1
    return _PropertyReferenceCounts(counts)


def _property_attribute_symbols(cfg: InterlockConfig) -> frozenset[tuple[str, str]]:
    symbols: set[tuple[str, str]] = set()
    for source in _iter_source_files(cfg):
        rel = cfg.relpath(source)
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=rel)
        except (OSError, SyntaxError):
            continue
        symbols.update(_property_attribute_symbols_from_tree(tree, rel))
    return frozenset(symbols)


def _property_attribute_symbols_from_tree(tree: ast.AST, relpath: str) -> set[tuple[str, str]]:
    if not isinstance(tree, ast.Module):
        return set()
    symbols: set[tuple[str, str]] = set()
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for child in node.body:
            if not isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if _has_property_decorator(child):
                symbols.add((relpath, f"{node.name}.{child.name}"))
    return symbols


def _has_property_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        parts = _dotted_parts(target)
        if parts and parts[-1] in {"property", "cached_property"}:
            return True
    return False


@dataclass(frozen=True, slots=True)
class _ReferenceAliases:
    modules: dict[str, str]
    objects: dict[str, tuple[str, str]]
    instances: dict[str, tuple[str, str]]


def _property_references_from_tree(
    cfg: InterlockConfig,
    tree: ast.AST,
    property_attributes: frozenset[tuple[str, str]] = frozenset(),
) -> list[tuple[str, str]]:
    if not isinstance(tree, ast.Module):
        return []
    module_aliases = _reference_aliases(cfg, tree)
    refs: list[tuple[str, str]] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            refs.extend(_references_from_scope(cfg, module_aliases, node, property_attributes))
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    refs.extend(
                        _references_from_scope(cfg, module_aliases, child, property_attributes)
                    )
        else:
            refs.extend(_resolved_references(cfg, module_aliases, node, property_attributes))
    return refs


def _references_from_scope(
    cfg: InterlockConfig,
    module_aliases: _ReferenceAliases,
    scope: ast.FunctionDef | ast.AsyncFunctionDef,
    property_attributes: frozenset[tuple[str, str]] = frozenset(),
) -> list[tuple[str, str]]:
    local_aliases = _scope_reference_aliases(cfg, module_aliases, scope)
    return _resolved_references(cfg, local_aliases, scope, property_attributes)


def _child_reference(
    cfg: InterlockConfig,
    aliases: _ReferenceAliases,
    child: ast.AST,
    call_func_ids: frozenset[int],
    property_attributes: frozenset[tuple[str, str]],
) -> tuple[str, str] | None:
    if isinstance(child, ast.Call):
        return _resolved_reference(cfg, aliases, child.func)
    if (
        isinstance(child, ast.Attribute)
        and isinstance(child.ctx, ast.Load)
        and id(child) not in call_func_ids
    ):
        ref = _resolved_reference(cfg, aliases, child)
        # `None in property_attributes` is False, so this also screens out misses.
        if ref in property_attributes:
            return ref
    return None


def _resolved_references(
    cfg: InterlockConfig,
    aliases: _ReferenceAliases,
    node: ast.AST,
    property_attributes: frozenset[tuple[str, str]] = frozenset(),
) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    call_func_ids = frozenset(
        id(child.func) for child in ast.walk(node) if isinstance(child, ast.Call)
    )
    for child in ast.walk(node):
        ref = _child_reference(cfg, aliases, child, call_func_ids, property_attributes)
        if ref is not None:
            refs.append(ref)
    return refs


def _reference_aliases(cfg: InterlockConfig, tree: ast.AST) -> _ReferenceAliases:
    modules: dict[str, str] = {}
    objects: dict[str, tuple[str, str]] = {}
    instances: dict[str, tuple[str, str]] = {}
    aliases = _ReferenceAliases(modules, objects, instances)
    ambiguous_modules: set[str] = set()
    ambiguous_objects: set[str] = set()
    if not isinstance(tree, ast.Module):
        return aliases
    for node in tree.body:
        if isinstance(node, ast.Import):
            _record_import_aliases(cfg, node, modules, ambiguous_modules)
        elif isinstance(node, ast.ImportFrom) and node.module:
            _record_import_from_aliases(
                cfg,
                node,
                aliases,
                ambiguous_modules,
                ambiguous_objects,
            )
    for node in tree.body:
        if isinstance(node, ast.Assign):
            _record_instance_aliases(cfg, aliases, node.targets, node.value)
        elif isinstance(node, ast.AnnAssign):
            _record_instance_aliases(cfg, aliases, (node.target,), node.value)
    return aliases


def _scope_reference_aliases(
    cfg: InterlockConfig,
    module_aliases: _ReferenceAliases,
    scope: ast.FunctionDef | ast.AsyncFunctionDef,
) -> _ReferenceAliases:
    local_modules: dict[str, str] = {}
    local_objects: dict[str, tuple[str, str]] = {}
    local_aliases = _ReferenceAliases(local_modules, local_objects, {})
    ambiguous_modules: set[str] = set()
    ambiguous_objects: set[str] = set()
    for node in ast.walk(scope):
        if isinstance(node, ast.Import):
            _record_import_aliases(cfg, node, local_modules, ambiguous_modules)
        elif isinstance(node, ast.ImportFrom) and node.module:
            _record_import_from_aliases(
                cfg,
                node,
                local_aliases,
                ambiguous_modules,
                ambiguous_objects,
            )
    aliases = _ReferenceAliases(
        {**module_aliases.modules, **local_modules},
        {**module_aliases.objects, **local_objects},
        dict(module_aliases.instances),
    )
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign):
            _record_instance_aliases(cfg, aliases, node.targets, node.value)
        elif isinstance(node, ast.AnnAssign):
            _record_instance_aliases(cfg, aliases, (node.target,), node.value)
    return aliases


def _record_import_aliases(
    cfg: InterlockConfig,
    node: ast.Import,
    modules: dict[str, str],
    ambiguous: set[str] | None = None,
) -> None:
    for alias in node.names:
        if _module_relpath(cfg, alias.name) is None:
            continue
        _record_unique_alias(modules, alias.asname or alias.name, alias.name, ambiguous)


def _record_import_from_aliases(
    cfg: InterlockConfig,
    node: ast.ImportFrom,
    aliases: _ReferenceAliases,
    ambiguous_modules: set[str] | None = None,
    ambiguous_objects: set[str] | None = None,
) -> None:
    if node.module is None:
        return
    for alias in node.names:
        if alias.name == "*":
            continue
        local = alias.asname or alias.name
        imported_module = f"{node.module}.{alias.name}"
        if _module_relpath(cfg, imported_module) is not None:
            _record_unique_alias(aliases.modules, local, imported_module, ambiguous_modules)
            continue
        module_path = _module_relpath(cfg, node.module)
        if module_path is not None:
            _record_unique_alias(
                aliases.objects,
                local,
                (module_path, alias.name),
                ambiguous_objects,
            )


def _record_unique_alias(
    aliases: dict[str, _AliasTarget],
    local: str,
    target: _AliasTarget,
    ambiguous: set[str] | None,
) -> None:
    if ambiguous is not None and local in ambiguous:
        return
    existing = aliases.get(local)
    if existing is None:
        aliases[local] = target
    elif existing != target and ambiguous is not None:
        aliases.pop(local, None)
        ambiguous.add(local)
    else:
        aliases[local] = target


def _record_instance_aliases(
    cfg: InterlockConfig,
    aliases: _ReferenceAliases,
    targets: tuple[ast.expr, ...] | list[ast.expr],
    value: ast.expr | None,
) -> None:
    if not isinstance(value, ast.Call):
        return
    ref = _resolved_reference(cfg, aliases, value.func)
    if ref is None or not _looks_like_class_symbol(ref[1]):
        return
    for target in targets:
        if isinstance(target, ast.Name):
            aliases.instances[target.id] = ref


def _looks_like_class_symbol(symbol: str) -> bool:
    leaf = symbol.rsplit(".", maxsplit=1)[-1].lstrip("_")
    return bool(leaf) and leaf[0].isupper()


def _resolved_reference(
    cfg: InterlockConfig, aliases: _ReferenceAliases, node: ast.AST
) -> tuple[str, str] | None:
    ref: tuple[str, str] | None = None
    if isinstance(node, ast.Name):
        ref = aliases.objects.get(node.id)
    elif isinstance(node, ast.Attribute):
        parts = _dotted_parts(node)
        if len(parts) >= 2:
            if parts[0] in aliases.modules:
                module_parts = (*aliases.modules[parts[0]].split("."), *parts[1:])
                ref = _reference_for_module_parts(cfg, module_parts)
            elif parts[0] in aliases.objects:
                relpath, symbol = aliases.objects[parts[0]]
                ref = (relpath, ".".join((symbol, *parts[1:])))
            elif parts[0] in aliases.instances:
                relpath, symbol = aliases.instances[parts[0]]
                ref = (relpath, ".".join((symbol, *parts[1:])))
            else:
                ref = _reference_for_module_parts(cfg, parts)
    return ref


def _reference_for_module_parts(
    cfg: InterlockConfig, parts: tuple[str, ...]
) -> tuple[str, str] | None:
    for index in range(len(parts) - 1, 0, -1):
        relpath = _module_relpath(cfg, ".".join(parts[:index]))
        if relpath is not None:
            return relpath, ".".join(parts[index:])
    return None


def _dotted_parts(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        return (*_dotted_parts(node.value), node.attr)
    return ()


def _module_relpath(cfg: InterlockConfig, module: str) -> str | None:
    suffix = Path(*module.split(".")).with_suffix(".py")
    candidates = (cfg.project_root / suffix, cfg.src_dir / suffix)
    for path in candidates:
        if path.is_file():
            return cfg.relpath(path)
    return None


def _candidate_from_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    relpath: str,
    *,
    qualname: str | None = None,
) -> PropertyCandidate:
    strategies = _strategies_for_args(node)
    signals = _candidate_signals(node, strategies)

    return PropertyCandidate(
        path=relpath,
        name=node.name,
        line=node.lineno,
        score=max(signals.score, 0),
        reasons=tuple(signals.reasons),
        cautions=tuple(dict.fromkeys(signals.cautions)),
        strategies=strategies,
        qualname=qualname or node.name,
    )


def _candidate_signals(
    node: ast.FunctionDef | ast.AsyncFunctionDef, strategies: dict[str, str]
) -> _CandidateSignals:
    signals = _CandidateSignals()
    _add_strategy_signals(signals, strategies)
    _add_return_annotation_signal(signals, node)
    _add_name_signal(signals, node.name)
    _add_branch_signal(signals, node)
    _add_return_value_signal(signals, node)
    _add_side_effect_signals(signals, node)
    _add_boundary_signals(signals, node)
    return signals


def _add_strategy_signals(signals: _CandidateSignals, strategies: dict[str, str]) -> None:
    if strategies:
        signals.score += 3
        signals.reasons.append("typed generated inputs")
    if any(strategy == "tmp_path-derived Path" for strategy in strategies.values()):
        signals.score -= 2
        signals.cautions.append("filesystem fixture required")


def _add_return_annotation_signal(
    signals: _CandidateSignals, node: ast.FunctionDef | ast.AsyncFunctionDef
) -> None:
    if node.returns is not None:
        signals.score += 1
        signals.reasons.append("typed return")


def _add_name_signal(signals: _CandidateSignals, name: str) -> None:
    match = next((word for word in _PROPERTY_NAME_WORDS if word in name), None)
    if match is not None:
        signals.score += 3
        signals.reasons.append(f"name suggests invariant ({match})")


def _add_branch_signal(
    signals: _CandidateSignals, node: ast.FunctionDef | ast.AsyncFunctionDef
) -> None:
    branches = sum(1 for child in ast.walk(node) if isinstance(child, _BRANCH_NODES))
    if branches:
        signals.score += min(branches, 4)
        signals.reasons.append(f"{branches} branch point(s)")


def _add_return_value_signal(
    signals: _CandidateSignals, node: ast.FunctionDef | ast.AsyncFunctionDef
) -> None:
    if _returns_value(node):
        signals.score += 1
        signals.reasons.append("returns a value")


def _add_side_effect_signals(
    signals: _CandidateSignals, node: ast.FunctionDef | ast.AsyncFunctionDef
) -> None:
    signals.cautions.extend(_side_effect_cautions(node))
    if signals.cautions:
        signals.score -= min(len(signals.cautions), 4)
    else:
        signals.score += 2
        signals.reasons.append("no obvious side effects")


def _add_boundary_signals(
    signals: _CandidateSignals, node: ast.FunctionDef | ast.AsyncFunctionDef
) -> None:
    if isinstance(node, ast.AsyncFunctionDef):
        signals.score -= 2
        signals.cautions.append("async boundary")
    if node.name.startswith("cmd_"):
        signals.score -= 3
        signals.cautions.append("CLI command boundary")


def _strategies_for_args(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, str]:
    strategies: dict[str, str] = {}
    args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    for arg in args:
        if arg.arg in {"self", "cls"} or arg.annotation is None:
            continue
        strategy = _strategy_for_annotation(ast.unparse(arg.annotation))
        if strategy is not None:
            strategies[arg.arg] = strategy
    return strategies


def _strategy_for_annotation(annotation: str) -> str | None:
    normalized = annotation.replace(" ", "")
    lower = normalized.lower()
    exact = _EXACT_STRATEGIES.get(lower)
    if exact is not None:
        return exact
    if lower.startswith(("list[", "sequence[")):
        return "st.lists(...)"
    if lower.startswith("tuple["):
        return "st.tuples(...)"
    if lower.startswith(("dict[", "mapping[")):
        return "st.dictionaries(...)"
    if lower.endswith(("path", ".path")):
        return "tmp_path-derived Path"
    return None


def _returns_value(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(child, ast.Return) and child.value is not None for child in ast.walk(node)
    )


def _side_effect_cautions(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    cautions: list[str] = []
    for child in ast.walk(node):
        cautions.extend(_node_side_effect_cautions(child))
    return cautions


def _node_side_effect_cautions(node: ast.AST) -> list[str]:
    if isinstance(node, ast.With | ast.AsyncWith):
        return ["context manager / resource boundary"]
    if isinstance(node, ast.Global):
        return ["mutates global state"]
    if isinstance(node, ast.Raise):
        return ["raises exceptions"]
    if isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign):
        return _assignment_cautions(node)
    if isinstance(node, ast.Call):
        return _call_side_effect_cautions(node)
    return []


def _call_side_effect_cautions(node: ast.Call) -> list[str]:
    call_name = _call_name(node.func)
    short_name = call_name.rsplit(".", 1)[-1]
    if _known_side_effect_call(call_name, short_name):
        return [f"possible side effect call: {call_name}"]
    if call_name.startswith(("os.", "subprocess.", "shutil.", "signal.")):
        return [f"system boundary: {call_name}"]
    return []


def _known_side_effect_call(call_name: str, short_name: str) -> bool:
    return (
        call_name in _SIDE_EFFECT_CALLS
        or short_name in _SIDE_EFFECT_CALLS
        or short_name in _SIDE_EFFECT_METHODS
    )


def _assignment_cautions(node: ast.Assign | ast.AnnAssign | ast.AugAssign) -> list[str]:
    targets: list[ast.AST] = list(node.targets) if isinstance(node, ast.Assign) else [node.target]
    cautions: list[str] = []
    for target in targets:
        name = _call_name(target)
        if name.startswith(("os.", "subprocess.", "shutil.", "signal.", "sys.")):
            cautions.append(f"system boundary assignment: {name}")
    return cautions


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _candidate_limit() -> int:
    raw = arg_value("--limit=", str(_DEFAULT_CANDIDATE_LIMIT))
    try:
        limit = int(raw)
    except ValueError:
        _fail_property_candidates("property-candidates: --limit must be an integer")
    if limit < 0:
        _fail_property_candidates("property-candidates: --limit must be >= 0")
    return limit


def _property_candidates_usage() -> str:
    return (
        "usage: interlocks property-candidates "
        "[--changed[=REF]] [--uncovered] [--limit=N] [--json]"
    )


def _property_candidates_error_payload(message: str) -> dict[str, object]:
    return {
        "command": "property-candidates",
        "error": message,
        "usage": _property_candidates_usage(),
        "expected_limit": "integer >= 0",
    }


def _fail_property_candidates(message: str) -> NoReturn:
    if ui.is_json():
        ui.print_json(_property_candidates_error_payload(message))
        raise SystemExit(1)
    fail_skip(message)
