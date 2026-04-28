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

BehaviorKind = Literal["cli", "config", "stage", "task", "doctor", "init", "meta", "evaluate"]

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
        "cli-version", "cli", "version command prints package version", "interlocks.cli:main"
    ),
    Behavior("cli-quiet", "cli", "quiet flag suppresses banner chrome", "interlocks.cli:main"),
    Behavior(
        "cli-config",
        "config",
        "config command prints resolved interlocks settings",
        "interlocks.cli:main",
    ),
    Behavior(
        "cli-evaluate-guidance",
        "evaluate",
        "evaluate prints actionable closure guidance",
        "interlocks.tasks.evaluate:cmd_evaluate",
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
        "interlocks.stages.setup_hooks:cmd_setup_hooks",
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
    for behavior_id in result.duplicate_behavior_ids:
        lines.append(
            f"invalid duplicate behavior ID: {behavior_id} — keep one live registry entry"
        )
    for behavior_id in result.uncovered_behavior_ids:
        lines.append(
            f"uncovered behavior ID: {behavior_id} — add `# req: {behavior_id}` "
            f"or `@req-{behavior_id}` to a runnable Scenario"
        )
    for scenario in result.stale_scenario_behaviors:
        lines.append(
            f"stale behavior ID: {scenario.behavior_id} at "
            f"{scenario.feature_path}:{scenario.scenario_line} — update marker or registry"
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
        if not stripped:
            pending_ids = []
            continue
        if stripped.startswith(("@", "#")):
            continue
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
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _duplicate_behavior_ids(behaviors: Sequence[Behavior]) -> tuple[str, ...]:
    counts = Counter(behavior.behavior_id for behavior in behaviors)
    return tuple(sorted(behavior_id for behavior_id, count in counts.items() if count > 1))
