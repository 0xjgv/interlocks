"""Behavior coverage registry, Gherkin marker parser, and graph validation."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from interlocks.config import InterlockConfig

BehaviorKind = Literal[
    "cli", "config", "stage", "task", "doctor", "init", "meta", "evaluate", "agents", "crash"
]

_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*")
_REQ_COMMENT_RE = re.compile(r"#\s*req\s*:\s*(?P<body>.*)$", re.IGNORECASE)
_REQ_TAG_RE = re.compile(r"(?:^|\s)@req-(?P<id>[A-Za-z0-9_.:-]+)")
_SCENARIO_RE = re.compile(r"^\s*Scenario(?: Outline)?:\s*(?P<title>.+?)\s*$", re.IGNORECASE)


@dataclass(frozen=True, order=True)
class Behavior:
    behavior_id: str
    kind: BehaviorKind
    summary: str
    public_symbol: str | None = None


@dataclass(frozen=True, order=True)
class ScenarioBehavior:
    behavior_id: str
    feature_path: Path
    scenario_title: str
    scenario_line: int


@dataclass(frozen=True)
class FeatureBehaviorParse:
    scenario_count: int
    scenario_behaviors: tuple[ScenarioBehavior, ...]


@dataclass(frozen=True)
class DuplicateBehavior:
    behavior_id: str
    entries: tuple[Behavior, ...]


@dataclass(frozen=True)
class BehaviorCoverageResult:
    behaviors: tuple[Behavior, ...]
    scenario_behaviors: tuple[ScenarioBehavior, ...]

    @property
    def live_ids(self) -> tuple[str, ...]:
        return tuple(sorted({behavior.behavior_id for behavior in self.behaviors}))

    @property
    def scenario_ids(self) -> tuple[str, ...]:
        return tuple(sorted({scenario.behavior_id for scenario in self.scenario_behaviors}))


@dataclass(frozen=True)
class BehaviorCoverageValidationResult:
    coverage: BehaviorCoverageResult
    uncovered_behavior_ids: tuple[str, ...] = ()
    stale_scenario_behaviors: tuple[ScenarioBehavior, ...] = ()
    duplicate_behavior_ids: tuple[str, ...] = ()

    @property
    def is_complete(self) -> bool:
        return not (
            self.uncovered_behavior_ids
            or self.stale_scenario_behaviors
            or self.duplicate_behavior_ids
        )


class BehaviorRegistry:
    def __init__(self, behaviors: Iterable[Behavior]) -> None:
        self._behaviors = tuple(sorted(behaviors))

    @property
    def behaviors(self) -> tuple[Behavior, ...]:
        return self._behaviors

    @property
    def live_ids(self) -> tuple[str, ...]:
        return tuple(sorted({behavior.behavior_id for behavior in self._behaviors}))

    @property
    def duplicates(self) -> tuple[DuplicateBehavior, ...]:
        by_id: dict[str, list[Behavior]] = defaultdict(list)
        for behavior in self._behaviors:
            by_id[behavior.behavior_id].append(behavior)
        return tuple(
            DuplicateBehavior(behavior_id, tuple(entries))
            for behavior_id, entries in sorted(by_id.items())
            if len(entries) > 1
        )


INTERLOCKS_BEHAVIORS: tuple[Behavior, ...] = (
    Behavior("cli-commands", "cli", "help lists supported public commands", "interlocks.cli:main"),
    Behavior(
        "cli-commands-advanced",
        "cli",
        "advanced help lists all commands including internal and alias commands",
        "interlocks.cli:main",
    ),
    Behavior(
        "cli-version", "cli", "version command prints package version", "interlocks.cli:main"
    ),
    Behavior(
        "cli-minimal-default",
        "cli",
        "minimal-by-default output rejects --quiet",
        "interlocks.cli:main",
    ),
    Behavior(
        "cli-command-help",
        "cli",
        "command-specific help is non-destructive",
        "interlocks.cli:main",
    ),
    Behavior(
        "cli-config",
        "config",
        "config command prints resolved interlocks settings",
        "interlocks.cli:main",
    ),
    Behavior(
        "cli-help-crash-reports",
        "cli",
        "help surfaces crash-report prompt behavior and cache directory",
        "interlocks.cli:main",
    ),
    Behavior(
        "cli-evaluate-guidance",
        "evaluate",
        "evaluate prints actionable closure guidance",
        "interlocks.tasks.evaluate:cmd_evaluate",
    ),
    Behavior(
        "cli-explain-all",
        "cli",
        "explain with no argument documents every command",
        "interlocks.tasks.explain:cmd_explain",
    ),
    Behavior(
        "cli-explain-one",
        "cli",
        "explain a single command prints just that command's prose",
        "interlocks.tasks.explain:cmd_explain",
    ),
    Behavior(
        "doctor-readiness",
        "doctor",
        "doctor reports setup readiness",
        "interlocks.tasks.doctor:cmd_doctor",
    ),
    Behavior(
        "doctor-setup-checklist",
        "doctor",
        "doctor reports setup checklist gaps",
        "interlocks.tasks.doctor:cmd_doctor",
    ),
    Behavior(
        "doctor-crash-reports",
        "doctor",
        "doctor surfaces the local crash-reports cache and consent",
        "interlocks.tasks.doctor:cmd_doctor",
    ),
    Behavior(
        "init-empty-dir",
        "init",
        "init scaffolds an empty project",
        "interlocks.tasks.init:cmd_init",
    ),
    Behavior(
        "init-preserve-existing",
        "init",
        "init preserves existing project files",
        "interlocks.tasks.init:cmd_init",
    ),
    Behavior(
        "agents-create-missing",
        "agents",
        "agents creates AGENTS.md and CLAUDE.md when absent",
        "interlocks.tasks.agents:cmd_agents",
    ),
    Behavior(
        "agents-append-when-missing",
        "agents",
        "agents appends the canonical block to docs without an interlocks reference",
        "interlocks.tasks.agents:cmd_agents",
    ),
    Behavior(
        "agents-idempotent",
        "agents",
        "agents leaves docs unchanged when the check stage is already documented",
        "interlocks.tasks.agents:cmd_agents",
    ),
    Behavior(
        "agents-append-when-stage-missing",
        "agents",
        "agents appends the canonical block when docs mention interlocks but not the check stage",
        "interlocks.tasks.agents:cmd_agents",
    ),
    Behavior(
        "meta-help-no-project", "meta", "help runs without project config", "interlocks.cli:main"
    ),
    Behavior(
        "meta-acceptance-noop",
        "meta",
        "acceptance no-ops when optional features are missing",
        "interlocks.tasks.acceptance:cmd_acceptance",
    ),
    Behavior(
        "meta-init-acceptance",
        "meta",
        "init-acceptance scaffolds feature files",
        "interlocks.tasks.init_acceptance:cmd_init_acceptance",
    ),
    Behavior(
        "meta-setup-hooks",
        "meta",
        "setup-hooks installs local hooks",
        "interlocks.stages.setup_hooks:cmd_hooks",
    ),
    Behavior(
        "meta-setup-skill-installs",
        "meta",
        "setup-skill writes the bundled SKILL.md",
        "interlocks.tasks.setup_skill:cmd_setup_skill",
    ),
    Behavior(
        "meta-setup-skill-idempotent",
        "meta",
        "setup-skill is idempotent on re-run",
        "interlocks.tasks.setup_skill:cmd_setup_skill",
    ),
    Behavior(
        "stage-check",
        "stage",
        "check runs local quality loop",
        "interlocks.stages.check:cmd_check",
    ),
    Behavior(
        "stage-pre-commit",
        "stage",
        "pre-commit checks staged Python files",
        "interlocks.stages.pre_commit:cmd_pre_commit",
    ),
    Behavior("stage-ci", "stage", "ci runs PR-grade verification", "interlocks.stages.ci:cmd_ci"),
    Behavior(
        "stage-nightly",
        "stage",
        "nightly runs long gates",
        "interlocks.stages.nightly:cmd_nightly",
    ),
    Behavior(
        "stage-baseline",
        "stage",
        "baseline shows the current quality floor",
        "interlocks.tasks.baseline_cmd:cmd_baseline",
    ),
    Behavior(
        "task-audit",
        "task",
        "audit reports dependency vulnerabilities",
        "interlocks.tasks.audit:cmd_audit",
    ),
    Behavior(
        "task-deps", "task", "deps reports dependency hygiene", "interlocks.tasks.deps:cmd_deps"
    ),
    Behavior(
        "task-arch", "task", "arch enforces import contracts", "interlocks.tasks.arch:cmd_arch"
    ),
    Behavior(
        "task-coverage",
        "task",
        "coverage enforces coverage threshold",
        "interlocks.tasks.coverage:cmd_coverage",
    ),
    Behavior(
        "task-coverage-uv-injection",
        "task",
        "coverage injects Coverage.py for uv-managed projects",
        "interlocks.tasks.coverage:task_coverage",
    ),
    Behavior(
        "task-crap",
        "task",
        "crap reports risky complexity and coverage combinations",
        "interlocks.tasks.crap:cmd_crap",
    ),
    Behavior(
        "task-mutation",
        "task",
        "mutation reports killed and surviving mutants",
        "interlocks.tasks.mutation:cmd_mutation",
    ),
    Behavior(
        "task-mutation-incremental",
        "task",
        "incremental mutation scopes mutmut to files changed vs mutation_since_ref",
        "interlocks.tasks.mutation:cmd_mutation",
    ),
    Behavior(
        "task-acceptance-required",
        "task",
        "acceptance fails when required scenarios are missing",
        "interlocks.tasks.acceptance:cmd_acceptance",
    ),
    Behavior(
        "task-acceptance-behavior-success",
        "task",
        "acceptance passes when live behavior IDs are covered",
        "interlocks.tasks.acceptance:cmd_acceptance",
    ),
    Behavior(
        "task-acceptance-behavior-uncovered",
        "task",
        "acceptance reports uncovered behavior IDs",
        "interlocks.tasks.acceptance:cmd_acceptance",
    ),
    Behavior(
        "task-acceptance-behavior-stale",
        "task",
        "acceptance reports stale scenario behavior IDs",
        "interlocks.tasks.acceptance:cmd_acceptance",
    ),
    Behavior(
        "task-acceptance-trace-advisory",
        "task",
        "acceptance trace evidence remains advisory",
        "interlocks.tasks.acceptance:cmd_acceptance",
    ),
    Behavior(
        "task-behavior-attribution-success",
        "task",
        "behavior-attribution exits 0 when every scenario claim is attributed",
        "interlocks.tasks.behavior_attribution:cmd_behavior_attribution",
    ),
    Behavior(
        "task-behavior-attribution-unattributed",
        "task",
        "behavior-attribution flags a scenario whose body did not reach the claimed symbol",
        "interlocks.tasks.behavior_attribution:cmd_behavior_attribution",
    ),
    Behavior(
        "task-behavior-attribution-unresolved",
        "task",
        "behavior-attribution flags a behavior symbol that no claiming scenario reached",
        "interlocks.tasks.behavior_attribution:cmd_behavior_attribution",
    ),
    Behavior(
        "task-lint-progressive-ratchet",
        "task",
        "lint counts ruff violations and gates on the progressive baseline cap",
        "interlocks.tasks.lint:cmd_lint_progressive",
    ),
    Behavior(
        "crash-boundary-prints-issue-url",
        "crash",
        "internal crash captures and prints a GitHub issue URL with the original traceback",
        "interlocks.crash.boundary:CrashBoundary",
    ),
    Behavior(
        "crash-user-error-no-capture",
        "crash",
        "user-facing config errors print a clean line and do not capture or open a URL",
        "interlocks.crash.boundary:CrashBoundary",
    ),
    Behavior(
        "crash-consent-off-suppresses-transport",
        "crash",
        "declining the crash-report prompt suppresses the URL but still writes a local crash file",
        "interlocks.crash.prompt:prompt_for_report",
    ),
    Behavior(
        "crash-dedup-suppresses-transport",
        "crash",
        "a repeated crash within the 30-day dedup window does not re-print the URL",
        "interlocks.crash.storage:should_suppress_transport",
    ),
    Behavior(
        "crash-gate-failure-no-capture",
        "crash",
        "a subprocess gate failure exits via SystemExit without entering capture",
        "interlocks.crash.boundary:CrashBoundary",
    ),
    Behavior(
        "greenfield-check-blocks",
        "stage",
        "check exits non-zero on a seeded legacy project with ruff lint failures",
        "interlocks.stages.check:cmd_check",
    ),
    Behavior(
        "greenfield-fix-plan-non-mutating",
        "task",
        "fix-plan writes .lintfix/plan.json and groups candidates without mutating the tree",
        "interlocks.tasks.fix_plan:cmd_fix_plan",
    ),
    Behavior(
        "greenfield-fix-rule-preview",
        "task",
        "fix-rule with default APPLY=0 previews a candidate without mutating the tree",
        "interlocks.tasks.fix_rule:cmd_fix_rule",
    ),
    Behavior(
        "greenfield-fix-optimize-non-mutating",
        "task",
        "fix-optimize selects a subset and writes optimize.json without mutating",
        "interlocks.tasks.fix_optimize:cmd_fix_optimize",
    ),
    Behavior(
        "greenfield-fix-annotate",
        "task",
        "fix-annotate emits workflow-command lines after a fix-plan run",
        "interlocks.tasks.fix_annotate:cmd_fix_annotate",
    ),
    Behavior(
        "greenfield-fix-metrics",
        "task",
        "fix-metrics rolls up per-run JSON into a single metrics.json",
        "interlocks.tasks.fix_metrics:cmd_fix_metrics",
    ),
    Behavior(
        "greenfield-setup-check",
        "task",
        "setup --check exits non-zero on an unadopted project and names missing artifacts",
        "interlocks.tasks.setup:cmd_setup",
    ),
    Behavior(
        "greenfield-doctor",
        "doctor",
        "doctor flags missing adoption steps on an unadopted project",
        "interlocks.tasks.doctor:cmd_doctor",
    ),
    Behavior(
        "fix-plan-classifies-i001-auto",
        "task",
        "fix-plan classifies I001 import-sort as auto on the changed file set",
        "interlocks.tasks.fix_plan:cmd_fix_plan",
    ),
    Behavior(
        "fix-plan-classifies-f401-escrow",
        "task",
        "fix-plan classifies F401 unused-import as escrow regardless of budget",
        "interlocks.tasks.fix_plan:cmd_fix_plan",
    ),
    Behavior(
        "fix-plan-skips-unsafe-only",
        "task",
        "fix-plan classifies unsafe-only diagnostics as skip with an 'unsafe' reason",
        "interlocks.tasks.fix_plan:cmd_fix_plan",
    ),
    Behavior(
        "fix-replay-writes-per-rule-stats",
        "task",
        "fix-replay writes per-rule statistics across a few-commit history",
        "interlocks.tasks.fix_replay:cmd_fix_replay",
    ),
    Behavior(
        "fix-optimize-empty-plan",
        "task",
        "fix-optimize selects no candidates when the plan is empty",
        "interlocks.tasks.fix_optimize:cmd_fix_optimize",
    ),
    Behavior(
        "fix-optimize-no-unsafe-in-unblock",
        "task",
        "fix-optimize never selects unsafe candidates under the unblock budget",
        "interlocks.tasks.fix_optimize:cmd_fix_optimize",
    ),
    Behavior(
        "fix-annotate-missing-plan",
        "task",
        "fix-annotate exits 0 with no output when .lintfix/plan.json is missing",
        "interlocks.tasks.fix_annotate:cmd_fix_annotate",
    ),
    Behavior(
        "fix-metrics-missing-inputs",
        "task",
        "fix-metrics writes a metrics.json with an all-false sources truthtable when no inputs",
        "interlocks.tasks.fix_metrics:cmd_fix_metrics",
    ),
    Behavior(
        "fix-optimize-rejects-escrow-with-policy-reason",
        "task",
        "fix-optimize rejects an escrow candidate with a policy-mode reason",
        "interlocks.tasks.fix_optimize:cmd_fix_optimize",
    ),
    Behavior(
        "fix-optimize-totals-match-selected-subset",
        "task",
        "fix-optimize totals equal the summed value and cost of the selected subset",
        "interlocks.tasks.fix_optimize:cmd_fix_optimize",
    ),
    Behavior(
        "unblock-alias-writes-artifact-set",
        "task",
        "the unblock alias runs fix-optimize and writes the full .lintfix artifact set",
        "interlocks.tasks.fix_optimize:cmd_fix_optimize",
    ),
    Behavior(
        "fix-optimize-annotate-emits-lines",
        "task",
        "fix-optimize --annotate emits GitHub Actions annotation lines inline",
        "interlocks.tasks.fix_optimize:cmd_fix_optimize",
    ),
    Behavior(
        "fix-optimize-metrics-writes-report",
        "task",
        "fix-optimize --metrics writes a metrics.json with populated plan and optimize sections",
        "interlocks.tasks.fix_optimize:cmd_fix_optimize",
    ),
)


INTERLOCKS_REGISTRY = BehaviorRegistry(INTERLOCKS_BEHAVIORS)


def behavior_registry_for_config(cfg: InterlockConfig) -> BehaviorRegistry:
    project = cfg.pyproject.get("project")
    if isinstance(project, dict) and project.get("name") == "interlocks":
        return INTERLOCKS_REGISTRY
    return BehaviorRegistry(())


def parse_scenario_behaviors(files: Iterable[Path]) -> tuple[ScenarioBehavior, ...]:
    return parse_feature_behaviors(files).scenario_behaviors


def parse_feature_behaviors(files: Iterable[Path]) -> FeatureBehaviorParse:
    scenario_count = 0
    scenario_behaviors: list[ScenarioBehavior] = []
    for path in sorted(files):
        parsed = _parse_feature_behaviors(path)
        scenario_count += parsed.scenario_count
        scenario_behaviors.extend(parsed.scenario_behaviors)
    return FeatureBehaviorParse(scenario_count, tuple(sorted(scenario_behaviors)))


def validate_behavior_coverage(
    behaviors: Iterable[Behavior],
    scenario_behaviors: Iterable[ScenarioBehavior],
) -> BehaviorCoverageValidationResult:
    coverage = BehaviorCoverageResult(tuple(sorted(behaviors)), tuple(sorted(scenario_behaviors)))
    live_ids = set(coverage.live_ids)
    scenario_ids = set(coverage.scenario_ids)
    duplicate_ids = _duplicate_behavior_ids(coverage.behaviors)
    uncovered = tuple(sorted(live_ids - scenario_ids))
    stale = tuple(s for s in coverage.scenario_behaviors if s.behavior_id not in live_ids)
    return BehaviorCoverageValidationResult(
        coverage=coverage,
        uncovered_behavior_ids=uncovered,
        stale_scenario_behaviors=stale,
        duplicate_behavior_ids=duplicate_ids,
    )


def behavior_coverage_for_config(
    cfg: InterlockConfig,
    files: Iterable[Path],
) -> BehaviorCoverageValidationResult:
    return behavior_coverage_for_parsed_features(cfg, parse_feature_behaviors(files))


def behavior_coverage_for_parsed_features(
    cfg: InterlockConfig,
    parsed: FeatureBehaviorParse,
) -> BehaviorCoverageValidationResult:
    registry = behavior_registry_for_config(cfg)
    if not registry.behaviors:
        return validate_behavior_coverage((), ())
    return validate_behavior_coverage(registry.behaviors, parsed.scenario_behaviors)


def format_behavior_coverage_failure(result: BehaviorCoverageValidationResult) -> str:
    lines = ["acceptance: behavior coverage incomplete — add or update Gherkin behavior markers"]
    lines.extend(
        f"invalid duplicate behavior ID: {behavior_id} — keep one live registry entry"
        for behavior_id in result.duplicate_behavior_ids
    )
    lines.extend(
        f"uncovered behavior ID: {behavior_id} — add `# req: {behavior_id}` "
        f"or `@req-{behavior_id}` to a runnable Scenario"
        for behavior_id in result.uncovered_behavior_ids
    )
    lines.extend(
        f"stale behavior ID: {scenario.behavior_id} at "
        f"{scenario.feature_path}:{scenario.scenario_line} — update marker or registry"
        for scenario in result.stale_scenario_behaviors
    )
    return "\n".join(lines)


def traceable_scenario_totals(files: Iterable[Path]) -> tuple[int, int]:
    return traceable_totals_for_parsed_features(parse_feature_behaviors(files))


def traceable_totals_for_parsed_features(parsed: FeatureBehaviorParse) -> tuple[int, int]:
    seen_scenarios = {
        (scenario.feature_path, scenario.scenario_line, scenario.scenario_title)
        for scenario in parsed.scenario_behaviors
    }
    return parsed.scenario_count, len(seen_scenarios)


def count_feature_scenarios(path: Path) -> int:
    return _parse_feature_behaviors(path).scenario_count


def _parse_feature_behaviors(path: Path) -> FeatureBehaviorParse:
    pending_ids: list[str] = []
    scenario_count = 0
    scenarios: list[ScenarioBehavior] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return FeatureBehaviorParse(0, ())
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        match = _SCENARIO_RE.match(stripped)
        if match is not None:
            scenario_count += 1
            title = match.group("title")
            for behavior_id in _dedupe_preserve_order(pending_ids):
                scenarios.append(ScenarioBehavior(behavior_id, path, title, line_number))
            pending_ids = []
            continue
        ids = _marker_ids(stripped)
        if ids:
            pending_ids.extend(ids)
            continue
        if not stripped or not stripped.startswith(("@", "#")):
            pending_ids = []
    return FeatureBehaviorParse(scenario_count, tuple(scenarios))


def _marker_ids(stripped: str) -> tuple[str, ...]:
    ids: list[str] = []
    comment = _REQ_COMMENT_RE.search(stripped)
    if comment is not None:
        ids.extend(_ID_RE.findall(comment.group("body")))
    ids.extend(match.group("id") for match in _REQ_TAG_RE.finditer(stripped))
    return tuple(_dedupe_preserve_order(ids))


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _duplicate_behavior_ids(behaviors: Sequence[Behavior]) -> tuple[str, ...]:
    counts = Counter(behavior.behavior_id for behavior in behaviors)
    return tuple(sorted(behavior_id for behavior_id, count in counts.items() if count > 1))
