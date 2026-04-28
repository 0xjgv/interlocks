"""Static quality checklist evaluator."""

from __future__ import annotations

import configparser
import json
import math
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from interlocks import ui
from interlocks.acceptance_status import feature_files as _shared_feature_files
from interlocks.acceptance_trace import format_trace_evidence, load_trace_evidence
from interlocks.behavior_coverage import (
    BehaviorCoverageValidationResult,
    FeatureBehaviorParse,
    behavior_coverage_for_parsed_features,
    behavior_registry_for_config,
    parse_feature_behaviors,
    traceable_totals_for_parsed_features,
)
from interlocks.config import InterlockConfig, coerce_float, load_optional_config
from interlocks.defaults_path import has_project_config
from interlocks.setup_state import CI_ACTION_NEEDLES, iter_workflow_bodies

Status = Literal["ok", "warn", "fail"]
ClosureKind = Literal["task", "stage"]

_CONTRACT_TYPES = frozenset({"forbidden", "layers", "acyclic", "independence"})
_ITEM_COUNT = 11
_MAX_TOTAL = _ITEM_COUNT * 3


@dataclass(frozen=True)
class ClosurePath:
    command: str
    kind: ClosureKind
    rationale: str


@dataclass(frozen=True)
class EvaluationItem:
    category: str
    score: int
    max_score: int = 3
    status: Status = "ok"
    detail: str = ""
    next_action: str | None = None
    closure: ClosurePath | None = None


@dataclass(frozen=True)
class EvaluationReport:
    items: list[EvaluationItem]
    total: int
    max_total: int
    verdict: str


@dataclass(frozen=True)
class CIEvidence:
    elapsed_seconds: float
    created_at: float
    passed: bool


_EVALUATE = ClosurePath("interlocks evaluate", "task", "static config and metadata checklist")
_ACCEPTANCE_TRACE = ClosurePath(
    "interlocks evaluate",
    "task",
    "traceability is feature metadata; interlocks acceptance only runs scenarios",
)
_CI_STAGE = ClosurePath("interlocks ci", "stage", "PR-grade merge gate owner")
_NIGHTLY_STAGE = ClosurePath("interlocks nightly", "stage", "long-running gate owner")


def cmd_evaluate() -> None:
    start = time.monotonic()
    cfg = load_optional_config()
    if cfg is None:
        _print_unreadable_config_report(start)
        return
    report = evaluate(cfg)

    ui.command_banner("evaluate", cfg)
    ui.section("Checklist")
    _print_checklist(report.items)

    ui.section("Score")
    ui.kv_block([
        ("total", f"{report.total} / {report.max_total}"),
        ("verdict", report.verdict),
    ])

    ui.section("Next Actions")
    actions = [_format_action(item) for item in report.items if item.next_action is not None]
    ui.message_list(actions, empty="No local evaluation gaps detected.")
    ui.command_footer(start)


def _print_unreadable_config_report(start: float) -> None:
    ui.command_banner("evaluate", None)
    ui.section("Checklist")
    print("  pyproject.toml unreadable — cannot evaluate local checklist.")
    ui.section("Score")
    ui.kv_block([("total", f"0 / {_MAX_TOTAL}"), ("verdict", "NEEDS WORK")])
    ui.section("Next Actions")
    ui.message_list(["Fix pyproject.toml syntax, then rerun `interlocks evaluate`."])
    ui.command_footer(start)


def evaluate(cfg: InterlockConfig) -> EvaluationReport:
    items = [
        _acceptance_item(cfg),
        _unit_tests_item(cfg),
        _coverage_item(cfg),
        _mutation_item(cfg),
        _complexity_item(cfg),
        _dependency_rules_item(cfg),
        _dependency_freshness_item(cfg),
        _security_item(),
        _audit_severity_item(cfg),
        _pr_speed_item(cfg),
        _ci_item(cfg),
    ]
    total = sum(item.score for item in items)
    max_total = sum(item.max_score for item in items)
    return EvaluationReport(
        items=items,
        total=total,
        max_total=max_total,
        verdict=_verdict(total, max_total),
    )


def _feature_files(cfg: InterlockConfig) -> list[Path]:
    return _shared_feature_files(cfg.features_dir)


def _feature_scenarios_with_traceability(feature_file: Path) -> tuple[int, int]:
    return traceable_totals_for_parsed_features(parse_feature_behaviors([feature_file]))


def _test_files(cfg: InterlockConfig) -> list[Path]:
    if not cfg.test_dir.is_dir():
        return []
    files = [*cfg.test_dir.rglob("test_*.py"), *cfg.test_dir.rglob("*_test.py")]
    return sorted(set(files))


def _coverage_branch_enabled(cfg: InterlockConfig) -> bool:
    coverage = _tool_section(cfg.pyproject, "coverage")
    if isinstance(coverage, dict):
        run = coverage.get("run")
        return isinstance(run, dict) and run.get("branch") is True

    coveragerc = cfg.project_root / ".coveragerc"
    if coveragerc.is_file():
        parser = configparser.ConfigParser()
        parser.read(coveragerc, encoding="utf-8")
        return parser.getboolean("run", "branch", fallback=False)

    return True


def _has_mutmut_config(cfg: InterlockConfig) -> bool:
    if isinstance(_tool_section(cfg.pyproject, "mutmut"), dict):
        return True
    return cfg.src_dir.exists() and bool(_test_files(cfg))


def _importlinter_contracts(cfg: InterlockConfig) -> list[dict[str, object]]:
    importlinter = _tool_section(cfg.pyproject, "importlinter")
    if isinstance(importlinter, dict):
        contracts = importlinter.get("contracts")
        if isinstance(contracts, list):
            return [contract for contract in contracts if isinstance(contract, dict)]
    return _sidecar_importlinter_contracts(cfg.project_root)


def _acceptance_item(cfg: InterlockConfig) -> EvaluationItem:
    feature_files = _feature_files(cfg)
    parsed_features = parse_feature_behaviors(feature_files)
    scenario_total, traced = traceable_totals_for_parsed_features(parsed_features)
    detail = _acceptance_detail(cfg)

    if not feature_files:
        return _item(
            "acceptance",
            0,
            detail,
            "Run `interlocks init-acceptance` to scaffold feature files.",
            closure=ClosurePath(
                "interlocks init-acceptance", "task", "scaffolds acceptance feature files"
            ),
        )
    if scenario_total == 0:
        return _item(
            "acceptance",
            1,
            detail,
            f"Add at least one Scenario under {cfg.features_dir_arg or 'features/'}.",
            closure=_ACCEPTANCE_TRACE,
        )
    return _score_acceptance(cfg, parsed_features, scenario_total, traced, detail)


def _score_acceptance(
    cfg: InterlockConfig,
    parsed_features: FeatureBehaviorParse,
    scenario_total: int,
    traced: int,
    detail: str,
) -> EvaluationItem:
    behavior_result = behavior_coverage_for_parsed_features(cfg, parsed_features)
    has_registry = bool(behavior_registry_for_config(cfg).behaviors)
    ci_wired = cfg.acceptance_runner != "off"

    if has_registry and not behavior_result.is_complete:
        return _item(
            "acceptance",
            1,
            detail,
            _behavior_coverage_action(behavior_result),
            closure=_ACCEPTANCE_TRACE,
        )
    if ci_wired and (has_registry or traced == scenario_total):
        return _item("acceptance", 3, detail)
    if not ci_wired:
        return _item(
            "acceptance",
            1,
            detail,
            "Enable acceptance runner so `interlocks ci` can run feature scenarios.",
            closure=ClosurePath(
                "interlocks acceptance", "task", "executes Gherkin scenarios outside evaluate"
            ),
        )
    missing = scenario_total - traced
    return _item(
        "acceptance",
        2 if traced else 1,
        detail,
        f"Add @req-* tags or # req: comments to {missing} acceptance scenario(s).",
        closure=_ACCEPTANCE_TRACE,
    )


def _acceptance_detail(cfg: InterlockConfig) -> str:
    evidence = load_trace_evidence(cfg.project_root)
    if evidence is None:
        return format_trace_evidence(None)
    reached = len(evidence.reached_symbols)
    total = reached + len(evidence.unreached_symbols)
    if evidence.failure is not None:
        return f"behavior markers + advisory trace failed ({reached}/{total} reached)"
    return f"behavior markers + advisory trace ({reached}/{total} reached)"


def _behavior_coverage_action(result: BehaviorCoverageValidationResult) -> str:
    if result.uncovered_behavior_ids:
        behavior_id = result.uncovered_behavior_ids[0]
        return f"Add `# req: {behavior_id}` or `@req-{behavior_id}` to a runnable Scenario."
    if result.stale_scenario_behaviors:
        scenario = result.stale_scenario_behaviors[0]
        return f"Update stale behavior marker `{scenario.behavior_id}` in {scenario.feature_path}."
    if result.duplicate_behavior_ids:
        return f"Remove duplicate behavior ID `{result.duplicate_behavior_ids[0]}` from registry."
    return "Add or update Gherkin behavior markers."


def _unit_tests_item(cfg: InterlockConfig) -> EvaluationItem:
    detail = "tests present and run through CI"
    if not _test_files(cfg):
        return _item(
            "unit-tests",
            0,
            detail,
            f"Add test_*.py or *_test.py files under {cfg.test_dir_arg}/.",
        )
    if _ci_source_contains("task_coverage(") or _ci_source_contains("task_test("):
        return _item("unit-tests", 3, detail)
    return _item("unit-tests", 1, detail, "Wire test execution into `interlocks ci`.")


def _coverage_item(cfg: InterlockConfig) -> EvaluationItem:
    threshold_positive = cfg.coverage_min > 0
    threshold_strong = cfg.coverage_min >= 80
    branch = _coverage_branch_enabled(cfg)
    ci_wired = _ci_source_contains("task_coverage(")
    detail = "branch coverage + threshold in CI"

    if threshold_strong and branch and ci_wired:
        return _item("coverage", 3, detail)
    if not threshold_positive:
        return _item("coverage", 0, detail, "Set coverage_min to at least 80.")
    if not threshold_strong:
        return _item(
            "coverage",
            2 if branch and ci_wired else 1,
            detail,
            "Raise coverage_min to at least 80.",
        )
    if not branch:
        return _item(
            "coverage",
            2 if ci_wired else 1,
            detail,
            "Enable branch coverage in [tool.coverage.run].",
        )
    return _item("coverage", 2, detail, "Wire task_coverage() into `interlocks ci`.")


def _mutation_item(cfg: InterlockConfig) -> EvaluationItem:
    configured = _has_mutmut_config(cfg)
    ci_enabled = cfg.run_mutation_in_ci or cfg.mutation_ci_mode != "off"
    enforced = cfg.enforce_mutation and cfg.mutation_min_score > 0
    detail = "mutmut configured + enforced"

    if configured and ci_enabled and enforced:
        return _item("mutation", 3, detail)
    if not configured:
        return _item(
            "mutation",
            0,
            detail,
            "Add [tool.mutmut] or make source/tests discoverable by mutmut defaults.",
            closure=_NIGHTLY_STAGE,
        )
    if not ci_enabled:
        return _item(
            "mutation",
            1,
            detail,
            'Set mutation_ci_mode = "incremental" or "full".',
            closure=_NIGHTLY_STAGE,
        )
    return _item(
        "mutation",
        2,
        detail,
        "Set enforce_mutation = true and mutation_min_score > 0.",
        closure=_NIGHTLY_STAGE,
    )


def _complexity_item(cfg: InterlockConfig) -> EvaluationItem:
    score, action = _complexity_score_action(cfg)
    return _item("complexity", score, "lizard + CRAP enforced", action)


def _dependency_rules_item(cfg: InterlockConfig) -> EvaluationItem:
    has_config = has_project_config(cfg, "importlinter", sidecars=(".importlinter", "setup.cfg"))
    default_available = _default_arch_contract_available(cfg)
    contracts = _importlinter_contracts(cfg)
    strong_contracts = any(_contract_type(contract) in _CONTRACT_TYPES for contract in contracts)
    ci_wired = _ci_source_contains("task_arch(") and (has_config or default_available)
    detail = "import-linter contracts in CI"

    if strong_contracts and ci_wired:
        return _item("deps", 3, detail)
    if not has_config and not default_available:
        return _item(
            "deps", 0, detail, "Add [tool.importlinter] contracts or Python-package src/test dirs."
        )
    if not strong_contracts:
        return _item(
            "deps",
            2 if ci_wired else 1,
            detail,
            "Add forbidden, layers, or acyclic import-linter contracts.",
        )
    return _item("deps", 2, detail, "Wire task_arch() into `interlocks ci`.")


def _dependency_freshness_item(cfg: InterlockConfig) -> EvaluationItem:
    detail = "outdated-package policy is explicit"
    closure = ClosurePath(
        cfg.dependency_freshness_command,
        "task",
        (
            "package-index freshness is explicit; "
            f"{cfg.dependency_freshness_stage} owns slow verification outside default PR CI"
        ),
    )
    if cfg.evaluate_dependency_freshness:
        return _item("deps-freshness", 3, detail)
    return _item(
        "deps-freshness",
        0,
        detail,
        (
            "Set evaluate_dependency_freshness = true and run "
            f"`{cfg.dependency_freshness_command}` outside default PR CI."
        ),
        closure=closure,
    )


def _security_item() -> EvaluationItem:
    audit_exposed = _cli_source_contains('"audit"')
    audit_in_ci = _ci_source_contains("task_audit(")
    deps_in_ci = _ci_source_contains("task_deps(")
    detail = "audit + dep hygiene in CI"

    if audit_exposed and audit_in_ci and deps_in_ci:
        return _item("security", 3, detail)
    if not audit_exposed:
        return _item("security", 0, detail, "Expose `interlocks audit` and task_audit().")
    if not audit_in_ci:
        return _item(
            "security",
            2 if deps_in_ci else 1,
            detail,
            "Wire task_audit() into `interlocks ci`.",
        )
    return _item("security", 2, detail, "Wire task_deps() into `interlocks ci`.")


def _audit_severity_item(cfg: InterlockConfig) -> EvaluationItem:
    audit_exposed = _cli_source_contains('"audit"')
    audit_in_ci = _ci_source_contains("task_audit(")
    detail = "severity threshold for vulnerability audit"
    closure = ClosurePath("interlocks audit", "task", "vulnerability audit owns severity policy")

    if not audit_exposed:
        return _item(
            "audit-severity",
            0,
            detail,
            "Expose `interlocks audit` before configuring severity policy.",
            closure=closure,
        )
    if not audit_in_ci:
        return _item(
            "audit-severity",
            1,
            detail,
            "Wire task_audit() into `interlocks ci` before relying on severity policy.",
            closure=_CI_STAGE,
        )
    if cfg.audit_severity_threshold is not None:
        return _item("audit-severity", 3, detail)
    return _item(
        "audit-severity",
        2,
        detail,
        'Set audit_severity_threshold = "high" for explicit high-severity policy.',
        closure=closure,
    )


def _pr_speed_item(cfg: InterlockConfig) -> EvaluationItem:
    detail = "CI runtime budget + fresh evidence"
    if cfg.pr_ci_runtime_budget_seconds <= 0:
        return _item(
            "pr-speed",
            0,
            detail,
            "Set pr_ci_runtime_budget_seconds to declare the PR CI runtime budget.",
            closure=_CI_STAGE,
        )

    evidence = _read_ci_evidence(cfg)
    if evidence is None:
        return _item(
            "pr-speed",
            1,
            detail,
            (
                "Run `interlocks ci` to write timing evidence to "
                f"{cfg.relpath(cfg.ci_evidence_path)}."
            ),
            closure=_CI_STAGE,
        )

    age_hours = _evidence_age_hours(evidence)
    if age_hours > cfg.pr_ci_evidence_max_age_hours:
        return _item(
            "pr-speed",
            1,
            detail,
            (
                "Refresh stale CI timing evidence; "
                f"current age is {age_hours:.1f}h and max is "
                f"{cfg.pr_ci_evidence_max_age_hours}h."
            ),
            closure=_CI_STAGE,
        )
    if not evidence.passed:
        return _item(
            "pr-speed",
            1,
            detail,
            "Fix failing `interlocks ci` evidence before scoring PR speed.",
            closure=_CI_STAGE,
        )
    if evidence.elapsed_seconds <= cfg.pr_ci_runtime_budget_seconds:
        return _item("pr-speed", 3, detail)
    return _item(
        "pr-speed",
        2,
        detail,
        (
            f"Reduce `interlocks ci` runtime from {evidence.elapsed_seconds:.1f}s "
            f"to <= {cfg.pr_ci_runtime_budget_seconds}s."
        ),
        closure=_CI_STAGE,
    )


def _ci_item(cfg: InterlockConfig) -> EvaluationItem:
    bodies = iter_workflow_bodies(cfg.project_root)
    local_command = any("interlocks ci" in body for body in bodies)
    action_reference = any(any(needle in body for needle in CI_ACTION_NEEDLES) for body in bodies)
    detail = "workflow calls interlocks ci"

    if local_command:
        return _item("ci", 3, detail)
    if action_reference:
        return _item(
            "ci", 2, detail, "Make workflow command explicitly reproducible as `interlocks ci`."
        )
    if bodies:
        return _item("ci", 1, detail, "Add `interlocks ci` to a GitHub Actions workflow.")
    return _item("ci", 0, detail, "Add .github/workflows CI that runs `interlocks ci`.")


def _print_checklist(items: list[EvaluationItem]) -> None:
    detail_width = max(len(item.detail) for item in items)
    for item in items:
        print(
            f"  [{item.category}]".ljust(21)
            + f"{item.detail:<{detail_width}}  {item.score}/{item.max_score}"
        )


def _item(
    category: str,
    score: int,
    detail: str,
    next_action: str | None = None,
    *,
    closure: ClosurePath | None = None,
) -> EvaluationItem:
    status: Status = "ok" if score == 3 else "fail" if score == 0 else "warn"
    if next_action is not None and closure is None:
        closure = _CI_STAGE if category in _CI_CATEGORIES else _EVALUATE
    return EvaluationItem(
        category=category,
        score=score,
        status=status,
        detail=detail,
        next_action=next_action,
        closure=closure,
    )


def _format_action(item: EvaluationItem) -> str:
    action = f"[{item.category}] {item.next_action}"
    if item.closure is None:
        return action
    return (
        f"{action} Close with `{item.closure.command}` "
        f"({item.closure.kind}) — {item.closure.rationale}."
    )


def _traceability_totals(feature_files: list[Path]) -> tuple[int, int]:
    return traceable_totals_for_parsed_features(parse_feature_behaviors(feature_files))


def _read_ci_evidence(cfg: InterlockConfig) -> CIEvidence | None:
    try:
        data = json.loads(cfg.ci_evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    elapsed = coerce_float(data.get("elapsed_seconds"))
    created_at = coerce_float(data.get("created_at"))
    passed = data.get("passed")
    if elapsed is None or created_at is None or not isinstance(passed, bool):
        return None
    return CIEvidence(elapsed_seconds=elapsed, created_at=created_at, passed=passed)


def _evidence_age_hours(evidence: CIEvidence) -> float:
    return max(0.0, (time.time() - evidence.created_at) / 3600)


def _tool_section(pyproject: dict[str, Any], name: str) -> object:
    tool = pyproject.get("tool")
    if not isinstance(tool, dict):
        return None
    return tool.get(name)


def _complexity_score_action(cfg: InterlockConfig) -> tuple[int, str | None]:
    thresholds_ready = _complexity_thresholds_ready(cfg)
    ci_wired = _complexity_ci_wired()

    if thresholds_ready and cfg.enforce_crap and ci_wired:
        return 3, None
    if not thresholds_ready:
        return _missing_complexity_threshold_action(cfg)
    if not cfg.enforce_crap:
        return _advisory_complexity_action(ci_wired)
    return 2, "Wire task_complexity() and cmd_crap() into `interlocks ci`."


def _complexity_thresholds_ready(cfg: InterlockConfig) -> bool:
    return _has_complexity_thresholds(cfg) and _positive_finite(cfg.crap_max)


def _missing_complexity_threshold_action(cfg: InterlockConfig) -> tuple[int, str]:
    has_any_threshold = _has_complexity_thresholds(cfg) or _positive_finite(cfg.crap_max)
    return (
        1 if has_any_threshold else 0,
        "Set positive complexity_max_* and crap_max thresholds.",
    )


def _advisory_complexity_action(ci_wired: bool) -> tuple[int, str]:
    return 2 if ci_wired else 1, "Set enforce_crap = true."


def _complexity_ci_wired() -> bool:
    return _ci_source_contains("task_complexity(") and _ci_source_contains("cmd_crap(")


def _has_complexity_thresholds(cfg: InterlockConfig) -> bool:
    return all(
        _positive_finite(value)
        for value in (cfg.complexity_max_ccn, cfg.complexity_max_args, cfg.complexity_max_loc)
    )


def _positive_finite(value: int | float) -> bool:
    return math.isfinite(float(value)) and value > 0


def _contract_type(contract: dict[str, object]) -> str:
    value = contract.get("type")
    return value.lower() if isinstance(value, str) else ""


def _default_arch_contract_available(cfg: InterlockConfig) -> bool:
    return (
        (cfg.src_dir / "__init__.py").is_file()
        and (cfg.test_dir / "__init__.py").is_file()
        and cfg.src_dir.name != cfg.test_dir.name
    )


def _sidecar_importlinter_contracts(project_root: Path) -> list[dict[str, object]]:
    contracts: list[dict[str, object]] = []
    for filename in (".importlinter", "setup.cfg"):
        path = project_root / filename
        if not path.is_file():
            continue
        parser = configparser.ConfigParser()
        parser.read(path, encoding="utf-8")
        for section in parser.sections():
            if "contract" not in section:
                continue
            contracts.append(dict(parser.items(section)))
    return contracts


def _ci_source_contains(needle: str) -> bool:
    return _source_contains(Path(__file__).parents[1] / "stages" / "ci.py", needle)


def _cli_source_contains(needle: str) -> bool:
    return _source_contains(Path(__file__).parents[1] / "cli.py", needle)


def _source_contains(path: Path, needle: str) -> bool:
    return needle in _read_source(path)


@lru_cache(maxsize=8)
def _read_source(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _verdict(total: int, max_total: int) -> str:
    ratio = total / max_total if max_total else 0
    if ratio >= 0.9:
        return "HEALTHY"
    if ratio >= 0.67:
        return "GAPS"
    return "NEEDS WORK"


_CI_CATEGORIES = frozenset({
    "unit-tests",
    "coverage",
    "complexity",
    "deps",
    "security",
    "audit-severity",
    "pr-speed",
    "ci",
})
