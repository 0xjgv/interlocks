"""Property tests for evaluate scorecard helpers."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given
from hypothesis import strategies as st

from interlocks.config import InterlockConfig
from interlocks.defaults_path import path as defaults_path
from interlocks.tasks import evaluate as evaluate_mod
from interlocks.tasks.evaluate import (
    _CI_CATEGORIES,
    _EVALUATE,
    CIEvidence,
    ClosurePath,
    EvaluationItem,
    _acceptance_item,
    _ci_evidence_inputs_are_stale,
    _ci_evidence_skipped,
    _ci_item,
    _complexity_score_action,
    _contract_type,
    _coverage_item,
    _dependency_rules_item,
    _format_action,
    _item,
    _latest_mutation_completed,
    _mutation_item,
    _mutation_rerun_action,
    _pr_speed_evidence_action,
    _pr_speed_item,
    _properties_item,
    _read_ci_evidence,
    _report_next_actions,
    _security_item,
    _tool_section,
    _verdict,
)

_CATEGORY = st.text(min_size=1, max_size=20)
_DETAIL = st.text(max_size=40)
_ACTION = st.text(min_size=1, max_size=80)
_PATH_PARTS = st.lists(
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=12),
    min_size=1,
    max_size=3,
).map(tuple)
_JSON_SCALAR = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-1_000, max_value=1_000),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-1_000, max_value=1_000),
    st.text(max_size=20),
)


def _cfg(root: Path) -> InterlockConfig:
    return InterlockConfig(
        project_root=root,
        src_dir=root / "src",
        test_dir=root / "tests",
        test_runner="pytest",
        test_invoker="python",
        properties_dir=root / "properties",
        ci_evidence_path=root / ".interlocks" / "ci.json",
    )


@given(has_pyproject=st.booleans())
def test_report_next_actions_only_bootstraps_missing_pyproject(has_pyproject: bool) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        if has_pyproject:
            (root / "pyproject.toml").write_text(
                "[project]\nname = 'probe'\nversion = '0.0.0'\n",
                encoding="utf-8",
            )
        cfg = _cfg(root)

        actions = _report_next_actions(cfg)

    assert bool(actions) is not has_pyproject
    if actions:
        assert "interlocks init" in actions[0]


@given(
    total=st.integers(min_value=0, max_value=10_000),
    max_total=st.integers(min_value=1, max_value=10_000),
)
def test_verdict_matches_score_ratio(total: int, max_total: int) -> None:
    verdict = _verdict(total, max_total)
    ratio = total / max_total

    if ratio >= 0.9:
        assert verdict == "HEALTHY"
    elif ratio >= 0.67:
        assert verdict == "GAPS"
    else:
        assert verdict == "NEEDS WORK"


@given(category=_CATEGORY, score=st.integers(min_value=0, max_value=3), detail=_DETAIL)
def test_item_status_tracks_score(category: str, score: int, detail: str) -> None:
    item = _item(category, score, detail)

    assert item.status == ("ok" if score == 3 else "fail" if score == 0 else "warn")
    assert item.closure is None


@given(
    category=st.sampled_from([*sorted(_CI_CATEGORIES), "acceptance", "deps-freshness"]),
    action=_ACTION,
)
def test_item_next_action_defaults_to_owner_closure(category: str, action: str) -> None:
    item = _item(category, 1, "detail", action)

    assert item.closure is not None
    if category in _CI_CATEGORIES:
        assert item.closure.command == "interlocks ci"
        assert item.closure.kind == "stage"
    else:
        assert item.closure == _EVALUATE


@given(category=_CATEGORY, action=_ACTION)
def test_format_action_includes_closure_when_present(category: str, action: str) -> None:
    closure = ClosurePath("interlocks custom", "task", "custom rationale")
    item = EvaluationItem(
        category=category,
        score=1,
        detail="detail",
        next_action=action,
        closure=closure,
    )

    formatted = _format_action(item)

    assert formatted.startswith(f"[{category}] {action}")
    assert "Close with `interlocks custom` (task)" in formatted
    assert "custom rationale" in formatted


@given(
    elapsed=st.floats(allow_nan=False, allow_infinity=False, min_value=0, max_value=10_000),
    created_at=st.floats(allow_nan=False, allow_infinity=False, min_value=0, max_value=10_000),
    passed=st.booleans(),
    skipped=st.lists(st.text(min_size=1, max_size=20), max_size=8),
)
def test_read_ci_evidence_accepts_finite_numeric_payload(
    elapsed: float,
    created_at: float,
    passed: bool,
    skipped: list[str],
) -> None:
    with TemporaryDirectory() as raw_root:
        cfg = _cfg(Path(raw_root))
        cfg.ci_evidence_path.parent.mkdir(parents=True)
        cfg.ci_evidence_path.write_text(
            json.dumps({
                "elapsed_seconds": elapsed,
                "created_at": created_at,
                "passed": passed,
                "skipped": skipped,
            }),
            encoding="utf-8",
        )

        evidence = _read_ci_evidence(cfg)

    assert evidence is not None
    assert math.isclose(evidence.elapsed_seconds, elapsed)
    assert math.isclose(evidence.created_at, created_at)
    assert evidence.passed is passed
    assert evidence.skipped == tuple(sorted(set(skipped)))


@given(st.dictionaries(st.text(max_size=20), _JSON_SCALAR, max_size=8))
def test_read_ci_evidence_never_returns_invalid_evidence(
    payload: dict[str, object],
) -> None:
    with TemporaryDirectory() as raw_root:
        cfg = _cfg(Path(raw_root))
        cfg.ci_evidence_path.parent.mkdir(parents=True)
        cfg.ci_evidence_path.write_text(json.dumps(payload), encoding="utf-8")

        evidence = _read_ci_evidence(cfg)

    assert evidence is None or (
        math.isfinite(evidence.elapsed_seconds)
        and math.isfinite(evidence.created_at)
        and isinstance(evidence.passed, bool)
        and all(isinstance(label, str) for label in evidence.skipped)
    )


@given(labels=st.lists(st.text(min_size=1, max_size=20), max_size=12))
def test_ci_evidence_skipped_normalizes_string_labels(labels: list[str]) -> None:
    assert _ci_evidence_skipped({"skipped": labels}) == tuple(sorted(set(labels)))
    assert _ci_evidence_skipped({"skipped": ",".join(labels)}) == ()


@given(input_newer=st.booleans())
def test_ci_evidence_staleness_tracks_quality_inputs(input_newer: bool) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        cfg = _cfg(root)
        cfg.ci_evidence_path.parent.mkdir(parents=True)
        cfg.ci_evidence_path.write_text("{}", encoding="utf-8")
        paths = (
            root / "pyproject.toml",
            root / "src" / "sample.py",
            root / "tests" / "test_sample.py",
            root / "properties" / "test_sample_properties.py",
        )
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        base = 1_700_000_000.0
        os.utime(cfg.ci_evidence_path, (base, base))
        input_time = base + 1 if input_newer else base - 1
        for path in paths:
            os.utime(path, (input_time, input_time))

        stale = _ci_evidence_inputs_are_stale(cfg)

    assert stale is input_newer


@given(workflow=st.text(max_size=200))
def test_ci_item_score_stays_in_range(workflow: str) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        workflows = root / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").write_text(workflow, encoding="utf-8")

        item = _ci_item(_cfg(root))

    assert 0 <= item.score <= item.max_score
    assert item.category == "ci"


@given(detail=_DETAIL)
def test_acceptance_item_without_feature_files_requests_scaffold(detail: str) -> None:
    with TemporaryDirectory() as raw_root:
        cfg = _cfg(Path(raw_root))
        original_features = evaluate_mod._feature_files
        original_detail = evaluate_mod._acceptance_detail
        evaluate_mod._feature_files = lambda _cfg: []  # type: ignore[assignment]
        evaluate_mod._acceptance_detail = lambda _cfg: detail  # type: ignore[assignment]
        try:
            item = _acceptance_item(cfg)
        finally:
            evaluate_mod._feature_files = original_features
            evaluate_mod._acceptance_detail = original_detail

    assert item.category == "acceptance"
    assert item.score == 0
    assert item.detail == detail
    assert item.next_action == "Run `interlocks init-acceptance` to scaffold feature files."


@given(
    coverage_min=st.integers(min_value=0, max_value=100),
    branch=st.booleans(),
    ci_wired=st.booleans(),
)
def test_coverage_item_scores_threshold_branch_and_ci_state(
    coverage_min: int,
    branch: bool,
    ci_wired: bool,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "src",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
            coverage_min=coverage_min,
        )
        original_branch = evaluate_mod._coverage_branch_enabled
        original_ci = evaluate_mod._ci_source_contains
        evaluate_mod._coverage_branch_enabled = lambda _cfg: branch  # type: ignore[assignment]
        evaluate_mod._ci_source_contains = lambda needle: (
            ci_wired if needle == "task_coverage(" else False
        )  # type: ignore[assignment]
        try:
            item = _coverage_item(cfg)
        finally:
            evaluate_mod._coverage_branch_enabled = original_branch
            evaluate_mod._ci_source_contains = original_ci

    threshold_positive = coverage_min > 0
    threshold_strong = coverage_min >= 80
    if threshold_strong and branch and ci_wired:
        assert item.score == 3
        assert item.next_action is None
    elif not threshold_positive:
        assert item.score == 0
        assert item.next_action == "Set coverage_min to at least 80."
    elif not threshold_strong:
        assert item.score == (2 if branch and ci_wired else 1)
        assert item.next_action == "Raise coverage_min to at least 80."
    elif not branch:
        assert item.score == (2 if ci_wired else 1)
        assert item.next_action == "Enable branch coverage in [tool.coverage.run]."
    else:
        assert item.score == 2
        assert item.next_action == "Wire task_coverage() into `interlocks ci`."


@given(
    configured=st.booleans(),
    run_mutation_in_ci=st.booleans(),
    mutation_mode=st.sampled_from(["off", "incremental", "full"]),
    enforce_mutation=st.booleans(),
    min_score=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
)
def test_mutation_item_scores_config_ci_and_enforcement(
    configured: bool,
    run_mutation_in_ci: bool,
    mutation_mode: str,
    enforce_mutation: bool,
    min_score: float,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "src",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
            run_mutation_in_ci=run_mutation_in_ci,
            mutation_ci_mode=mutation_mode,  # type: ignore[arg-type]
            enforce_mutation=enforce_mutation,
            mutation_min_score=min_score,
        )
        original = evaluate_mod._has_mutmut_config
        original_completed = evaluate_mod._latest_mutation_completed
        evaluate_mod._has_mutmut_config = lambda _cfg: configured  # type: ignore[assignment]
        evaluate_mod._latest_mutation_completed = lambda _cfg: None  # type: ignore[assignment]
        try:
            item = _mutation_item(cfg)
        finally:
            evaluate_mod._has_mutmut_config = original
            evaluate_mod._latest_mutation_completed = original_completed

    ci_enabled = run_mutation_in_ci or mutation_mode != "off"
    enforced = enforce_mutation and min_score > 0
    if configured and ci_enabled and enforced:
        assert item.score == 3
        assert item.next_action is None
    elif not configured:
        assert item.score == 0
        assert item.next_action is not None and "Add [tool.mutmut]" in item.next_action
    elif not ci_enabled:
        assert item.score == 1
        assert item.next_action == 'Set mutation_ci_mode = "incremental" or "full".'
    else:
        assert item.score == 2
        assert item.next_action == "Set enforce_mutation = true and mutation_min_score > 0."


@given(completed=st.one_of(st.none(), st.booleans()))
def test_mutation_item_partial_evidence_reduces_score(completed: bool | None) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "src",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
            run_mutation_in_ci=True,
            mutation_ci_mode="full",
            enforce_mutation=True,
            mutation_min_score=80.0,
        )
        original = evaluate_mod._has_mutmut_config
        original_completed = evaluate_mod._latest_mutation_completed
        evaluate_mod._has_mutmut_config = lambda _cfg: True  # type: ignore[assignment]
        evaluate_mod._latest_mutation_completed = lambda _cfg: completed  # type: ignore[assignment]
        try:
            item = _mutation_item(cfg)
        finally:
            evaluate_mod._has_mutmut_config = original
            evaluate_mod._latest_mutation_completed = original_completed

    if completed is False:
        assert item.score == 2
        assert item.status == "warn"
        assert item.next_action is not None and "Rerun `interlocks mutation" in item.next_action
    else:
        assert item.score == 3
        assert item.status == "ok"
        assert item.next_action is None


@given(
    min_score=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
    max_runtime=st.integers(min_value=0, max_value=10_000),
    no_results=st.booleans(),
)
def test_mutation_rerun_action_only_suggests_changed_only_for_no_results(
    min_score: float,
    max_runtime: int,
    no_results: bool,
) -> None:
    cfg = InterlockConfig(
        project_root=Path.cwd(),
        src_dir=Path("src"),
        test_dir=Path("tests"),
        test_runner="pytest",
        test_invoker="python",
        mutation_min_score=min_score,
        mutation_max_runtime=max_runtime,
    )

    action = _mutation_rerun_action(cfg, no_results=no_results)

    assert f"interlocks mutation --min-score={min_score:.0f}" in action
    assert f"--max-runtime={max_runtime}" in action
    assert ("--changed-only" in action) is no_results


@given(completed=st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=20)))
def test_latest_mutation_completed_accepts_only_boolean_evidence(completed: object) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        evidence = root / ".interlocks/mutation.json"
        evidence.parent.mkdir()
        evidence.write_text(json.dumps({"completed": completed}), encoding="utf-8")
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "src",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
        )

        expected = completed if isinstance(completed, bool) else None
        assert _latest_mutation_completed(cfg) is expected


def test_latest_mutation_completed_treats_stale_evidence_as_incomplete() -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        evidence = root / ".interlocks/mutation.json"
        evidence.parent.mkdir()
        evidence.write_text(json.dumps({"completed": True}), encoding="utf-8")
        stats = root / "mutants/mutmut-stats.json"
        stats.parent.mkdir()
        stats.write_text("{}", encoding="utf-8")
        os.utime(evidence, (1, 1))
        os.utime(stats, (2, 2))
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "src",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
        )

        assert _latest_mutation_completed(cfg) is False


@given(
    has_config=st.booleans(),
    default_available=st.booleans(),
    strong_contract=st.booleans(),
    ci_source_contains=st.booleans(),
)
def test_dependency_rules_item_scores_contracts_and_ci_wiring(
    has_config: bool,
    default_available: bool,
    strong_contract: bool,
    ci_source_contains: bool,
) -> None:
    with TemporaryDirectory() as raw_root:
        cfg = _cfg(Path(raw_root))
        original_has_project = evaluate_mod.has_project_config
        original_default = evaluate_mod._default_arch_contract_available
        original_contracts = evaluate_mod._importlinter_contracts
        original_ci = evaluate_mod._ci_source_contains
        evaluate_mod.has_project_config = lambda *_args, **_kwargs: has_config  # type: ignore[assignment]
        evaluate_mod._default_arch_contract_available = lambda _cfg: default_available  # type: ignore[assignment]
        evaluate_mod._importlinter_contracts = lambda _cfg: [  # type: ignore[assignment]
            {"type": "forbidden" if strong_contract else "unknown"}
        ]
        evaluate_mod._ci_source_contains = lambda needle: (  # type: ignore[assignment]
            ci_source_contains if needle == "task_arch(" else False
        )
        try:
            item = _dependency_rules_item(cfg)
        finally:
            evaluate_mod.has_project_config = original_has_project
            evaluate_mod._default_arch_contract_available = original_default
            evaluate_mod._importlinter_contracts = original_contracts
            evaluate_mod._ci_source_contains = original_ci

    ci_wired = ci_source_contains and (has_config or default_available)
    if strong_contract and ci_wired:
        assert item.score == 3
        assert item.next_action is None
    elif not has_config and not default_available:
        assert item.score == 0
    elif not strong_contract:
        assert item.score == (2 if ci_wired else 1)
        assert item.next_action == "Add forbidden, layers, or acyclic import-linter contracts."
    else:
        assert item.score == 2
        assert item.next_action == "Wire task_arch() into `interlocks ci`."


@given(parts=_PATH_PARTS)
def test_properties_item_scaffold_action_uses_configured_dir(
    parts: tuple[str, ...],
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        properties_dir = root.joinpath(*parts)
        properties_dir.mkdir(parents=True)
        (properties_dir / "test_example_properties.py").write_bytes(
            defaults_path("properties_test_example.py").read_bytes()
        )
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "src",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
            properties_dir=properties_dir,
        )

        item = _properties_item(cfg)

    expected_dir = "/".join(parts)
    assert item.category == "properties"
    assert item.score == 1
    assert item.next_action == (
        f"Replace {expected_dir}/test_example_properties.py with domain invariants."
    )


@given(
    budget=st.integers(min_value=0, max_value=120),
    evidence_state=st.sampled_from(["missing", "stale", "failed", "skipped", "slow", "ok"]),
)
def test_pr_speed_item_scores_budget_and_ci_evidence_state(
    budget: int,
    evidence_state: str,
) -> None:
    max_age = 24
    evidence = (
        None
        if evidence_state == "missing"
        else CIEvidence(
            elapsed_seconds=(budget + 1 if evidence_state == "slow" else max(0, budget - 1)),
            created_at=1.0,
            passed=evidence_state != "failed",
            skipped=("mutation",) if evidence_state == "skipped" else (),
        )
    )
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "src",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
            pr_ci_runtime_budget_seconds=budget,
            pr_ci_evidence_max_age_hours=max_age,
            ci_evidence_path=root / ".interlocks" / "ci.json",
        )
        original_read = evaluate_mod._read_ci_evidence
        original_age = evaluate_mod._evidence_age_hours
        original_input_stale = evaluate_mod._ci_evidence_inputs_are_stale
        evaluate_mod._read_ci_evidence = lambda _cfg: evidence  # type: ignore[assignment]
        evaluate_mod._ci_evidence_inputs_are_stale = lambda _cfg: False  # type: ignore[assignment]
        evaluate_mod._evidence_age_hours = lambda _evidence: (
            max_age + 1 if evidence_state == "stale" else 0
        )  # type: ignore[assignment]
        try:
            item = _pr_speed_item(cfg)
        finally:
            evaluate_mod._read_ci_evidence = original_read
            evaluate_mod._evidence_age_hours = original_age
            evaluate_mod._ci_evidence_inputs_are_stale = original_input_stale

    if budget <= 0:
        assert item.score == 0
        assert (
            item.next_action is not None and "Set pr_ci_runtime_budget_seconds" in item.next_action
        )
    elif evidence_state == "missing":
        assert item.score == 1
        assert item.next_action is not None and "Run `interlocks ci`" in item.next_action
    elif evidence_state == "stale":
        assert item.score == 1
        assert (
            item.next_action is not None and "Refresh stale CI timing evidence" in item.next_action
        )
    elif evidence_state == "failed":
        assert item.score == 1
        assert item.next_action == "Fix failing `interlocks ci` evidence before scoring PR speed."
    elif evidence_state == "skipped":
        assert item.score == 1
        assert item.next_action == (
            "Run `interlocks ci` without --skip to write full timing evidence."
        )
    elif evidence_state == "slow":
        assert item.score == 2
        assert (
            item.next_action is not None and "Reduce `interlocks ci` runtime" in item.next_action
        )
    else:
        assert item.score == 3
        assert item.next_action is None


@given(
    refresh_action=st.one_of(st.none(), st.text(min_size=1, max_size=80)),
    passed=st.booleans(),
    skipped=st.one_of(
        st.just(()),
        st.tuples(st.sampled_from(["coverage", "mutation", "properties"])),
    ),
)
def test_pr_speed_evidence_action_prioritizes_refresh_failure_then_skips(
    refresh_action: str | None,
    passed: bool,
    skipped: tuple[str, ...],
) -> None:
    cfg = InterlockConfig(
        project_root=Path(),
        src_dir=Path("src"),
        test_dir=Path("tests"),
        test_runner="pytest",
        test_invoker="python",
    )
    evidence = CIEvidence(1.0, 1.0, passed=passed, skipped=skipped)
    original_refresh = evaluate_mod._ci_evidence_refresh_action
    evaluate_mod._ci_evidence_refresh_action = (  # type: ignore[assignment]
        lambda _cfg, _evidence: refresh_action
    )
    try:
        item = _pr_speed_evidence_action(cfg, evidence, "detail")
    finally:
        evaluate_mod._ci_evidence_refresh_action = original_refresh

    if refresh_action is not None:
        assert item is not None
        assert item.next_action == refresh_action
    elif not passed:
        assert item is not None
        assert item.next_action == "Fix failing `interlocks ci` evidence before scoring PR speed."
    elif skipped:
        assert item is not None
        assert item.next_action == (
            "Run `interlocks ci` without --skip to write full timing evidence."
        )
    else:
        assert item is None


@given(
    tool_value=st.one_of(_JSON_SCALAR, st.dictionaries(st.text(max_size=10), _JSON_SCALAR)),
    tool_is_table=st.booleans(),
    name=st.text(min_size=1, max_size=20),
)
def test_tool_section_returns_named_tool_table_only(
    tool_value: object,
    tool_is_table: bool,
    name: str,
) -> None:
    tool = {name: tool_value} if tool_is_table else tool_value
    pyproject = {"tool": tool}

    assert _tool_section(pyproject, name) == (tool.get(name) if isinstance(tool, dict) else None)


@given(value=st.one_of(_JSON_SCALAR, st.text(max_size=20)))
def test_contract_type_lowercases_string_type_only(value: object) -> None:
    contract = {"type": value}

    assert _contract_type(contract) == (value.lower() if isinstance(value, str) else "")


@given(
    has_complexity_thresholds=st.booleans(),
    has_crap_threshold=st.booleans(),
    enforce_crap=st.booleans(),
    ci_wired=st.booleans(),
)
def test_complexity_score_action_follows_threshold_enforcement_and_ci_state(
    has_complexity_thresholds: bool,
    has_crap_threshold: bool,
    enforce_crap: bool,
    ci_wired: bool,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "src",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
            complexity_max_ccn=1 if has_complexity_thresholds else 0,
            complexity_max_args=1 if has_complexity_thresholds else 0,
            complexity_max_loc=1 if has_complexity_thresholds else 0,
            crap_max=1.0 if has_crap_threshold else 0.0,
            enforce_crap=enforce_crap,
        )
        original = evaluate_mod._ci_complexity_wired
        evaluate_mod._ci_complexity_wired = lambda: ci_wired  # type: ignore[assignment]
        try:
            score, action = _complexity_score_action(cfg)
        finally:
            evaluate_mod._ci_complexity_wired = original

    thresholds_ready = has_complexity_thresholds and has_crap_threshold
    partial = has_complexity_thresholds or has_crap_threshold
    if thresholds_ready and enforce_crap and ci_wired:
        assert (score, action) == (3, None)
    elif not thresholds_ready:
        assert score == (1 if partial else 0)
        assert action == "Set positive complexity_max_* and crap_max thresholds."
    elif not enforce_crap:
        assert score == (2 if ci_wired else 1)
        assert action == "Set enforce_crap = true."
    else:
        assert score == 2
        assert action == "Wire task_complexity() and cmd_crap() into `interlocks ci`."


@given(audit_exposed=st.booleans(), audit_in_ci=st.booleans(), deps_in_ci=st.booleans())
def test_security_item_scores_audit_and_dependency_ci_wiring(
    audit_exposed: bool,
    audit_in_ci: bool,
    deps_in_ci: bool,
) -> None:
    original_cli = evaluate_mod._cli_source_contains
    original_ci = evaluate_mod._ci_source_contains
    evaluate_mod._cli_source_contains = lambda needle: (
        audit_exposed if needle == '"audit"' else False
    )  # type: ignore[assignment]
    evaluate_mod._ci_source_contains = lambda needle: {  # type: ignore[assignment]
        "task_audit(": audit_in_ci,
        "task_deps(": deps_in_ci,
    }.get(needle, False)
    try:
        item = _security_item()
    finally:
        evaluate_mod._cli_source_contains = original_cli
        evaluate_mod._ci_source_contains = original_ci

    assert item.category == "security"
    if audit_exposed and audit_in_ci and deps_in_ci:
        assert item.score == 3
        assert item.next_action is None
    elif not audit_exposed:
        assert item.score == 0
        assert item.next_action == "Expose `interlocks audit` and task_audit()."
    elif not audit_in_ci:
        assert item.score == (2 if deps_in_ci else 1)
        assert item.next_action == "Wire task_audit() into `interlocks ci`."
    else:
        assert item.score == 2
        assert item.next_action == "Wire task_deps() into `interlocks ci`."
