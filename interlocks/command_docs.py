"""Structured documentation registry for every `interlocks` subcommand.

Pure data, stdlib only. Imports nothing from :mod:`interlocks.cli` to stay out
of the import cycle (``cli`` imports every ``cmd_*`` handler).

``CommandDoc.summary`` is the canonical one-line description; ``cli.TASK_GROUPS``
is derived from this registry and the CLI's compact handler map.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FlagSpec:
    """One CLI flag a subcommand accepts. Pure data — declared, not parsed.

    ``name`` carries the trailing ``=`` for value flags (``"--min="``) and no
    ``=`` for boolean flags (``"--apply"``), mirroring how ``arg_value`` and
    ``arg_flag_value`` callers spell the flag. ``default`` is the rendered
    default shown in ``<task> --help``.
    """

    name: str  # "--min=" for value flags, "--apply" for boolean flags
    kind: str  # "value" | "boolean" | "optional"
    default: str  # rendered default, e.g. "cfg.coverage_min" or "off"
    description: str


@dataclass(frozen=True)
class CommandDoc:
    """Rich, agent-facing documentation for one `interlocks` subcommand.

    Frozen + tuple fields, mirroring ``ConfigKeyDoc``. ``summary`` is the source
    of truth for the command's one-line description; ``exit_codes`` is a tuple of
    ``(code, meaning)`` pairs, kept coarse and hand-authored.
    """

    name: str
    summary: str
    when_to_use: str
    mutates: bool
    outputs: tuple[str, ...]
    exit_codes: tuple[tuple[int, str], ...]
    flags: tuple[FlagSpec, ...] = ()
    usage: str = ""
    mutates_note: str = ""


# Lives here, not in ``cli.py``, so ``tasks/explain.py`` can resolve aliases
# without importing ``cli`` (which would create an import cycle).
ALIASES: dict[str, str] = {
    "attribution": "behavior-attribution",
    "unblock": "fix-optimize",
}


def alias_suffix(name: str) -> str:
    """Render `` (alias: x)`` / `` (aliases: x, y)`` for a canonical command name."""
    aliases = aliases_for(name)
    if not aliases:
        return ""
    label = "alias" if len(aliases) == 1 else "aliases"
    return f" ({label}: {', '.join(aliases)})"


def aliases_for(name: str) -> list[str]:
    """Return aliases that resolve to a canonical command name."""
    return sorted(alias for alias, canonical in ALIASES.items() if canonical == name)


def command_index_payload(doc: CommandDoc) -> dict[str, object]:
    """Return the compact JSON row used by command discovery surfaces."""
    return {
        "name": doc.name,
        "summary": doc.summary,
        "aliases": aliases_for(doc.name),
    }


def command_doc_payload(doc: CommandDoc) -> dict[str, object]:
    """Return one command's full machine-readable contract."""
    return {
        "command": doc.name,
        "usage": f"usage: interlocks {command_usage(doc)}",
        "summary": doc.summary,
        "when_to_use": doc.when_to_use,
        "mutates": doc.mutates,
        "mutates_note": command_mutation_summary(doc),
        "outputs": list(doc.outputs),
        "aliases": aliases_for(doc.name),
        "flags": [
            {
                "name": flag.name,
                "kind": flag.kind,
                "default": flag.default,
                "description": flag.description,
            }
            for flag in doc.flags
        ],
        "exit_codes": [{"code": code, "meaning": meaning} for code, meaning in doc.exit_codes],
    }


def command_usage(doc: CommandDoc) -> str:
    """Return the command-specific usage tail for `interlocks <tail>`."""
    return doc.usage or doc.name


def command_mutation_summary(doc: CommandDoc) -> str:
    """Return human-facing mutation impact for `interlocks explain`."""
    return doc.mutates_note or ("yes" if doc.mutates else "no")


_NO_PYPROJECT = (2, "no pyproject.toml found")
_SKIP_FLAG = FlagSpec(
    "--skip=",
    "value",
    "",
    "comma-separated gate labels to skip, e.g. mutation or coverage",
)


COMMAND_DOCS: tuple[CommandDoc, ...] = (
    # ── Tasks ────────────────────────────────────────────────────────────
    CommandDoc(
        "fix",
        "Fix lint errors with ruff",
        "Run after edits to auto-fix lint violations before committing; mutates source in place.",
        mutates=True,
        outputs=(),
        exit_codes=(
            (0, "no lint errors remain"),
            (1, "unfixable errors found"),
            _NO_PYPROJECT,
        ),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
    ),
    CommandDoc(
        "fix-rule",
        "Rule-scoped fix: plan or apply a single ruff rule (e.g. --rule=I001)",
        "Unblock a PR blocked by one lint family without rewriting unrelated "
        "legacy code; plans by default, `--apply` mutates when the rule is auto-mode "
        "and the verifier passes.",
        mutates=True,
        outputs=(".lintfix/escrow/<rule>.patch", ".lintfix/failed.patch"),
        exit_codes=(
            (0, "plan or apply succeeded"),
            (1, "apply or verifier failed"),
            (2, "missing --rule or no pyproject.toml"),
        ),
        flags=(
            FlagSpec("--apply", "boolean", "off", "mutate source instead of planning"),
            FlagSpec("--base=", "value", "origin/main", "git ref to diff against"),
            FlagSpec("--budget=", "value", "unblock", "named budget profile"),
            FlagSpec("--rule=", "value", "", "the single ruff rule to fix (e.g. I001)"),
            FlagSpec("--verify-cmd=", "value", "", "command used to verify an apply"),
            FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),
        ),
    ),
    CommandDoc(
        "fix-plan",
        "Non-mutating fix plan over all fixable ruff rules; writes .lintfix/plan.json",
        "Preview the full fixable-rule landscape on the changed file set without "
        "touching the working tree.",
        mutates=False,
        outputs=(".lintfix/plan.json",),
        exit_codes=(
            (0, "plan written"),
            (1, "rule discovery failed"),
            _NO_PYPROJECT,
        ),
        flags=(
            FlagSpec("--base=", "value", "origin/main", "git ref to diff against"),
            FlagSpec("--budget=", "value", "unblock", "named budget profile"),
            FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),
        ),
    ),
    CommandDoc(
        "fix-replay",
        "Replay fix-plan across recent commits; writes .lintfix/replay.json",
        "Build replay history that weights rule values for `fix-optimize`; runs in "
        "isolated git worktrees, never mutates the project.",
        mutates=False,
        outputs=(".lintfix/replay.json",),
        exit_codes=(
            (0, "replay written"),
            (1, "replay failed"),
            _NO_PYPROJECT,
        ),
        flags=(
            FlagSpec("--base=", "value", "origin/main", "git ref to diff against"),
            FlagSpec("--budget=", "value", "unblock", "named budget profile"),
            FlagSpec("--n=", "value", "25", "number of commits to replay"),
            FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),
        ),
    ),
    CommandDoc(
        "fix-optimize",
        "Pick the highest-value lint/format subset under budget; writes the full "
        ".lintfix/ set (--annotate / --metrics for CI; --apply to mutate)",
        "The self-sufficient mutation planner — discovers fixable Ruff rules and "
        "per-file format diffs, picks the best subset under `--budget=` or "
        "`--mutation-budget=`, and writes the full .lintfix/ set; `--renovate` "
        "selects the explicit broad-cleanup profile.",
        mutates=True,
        outputs=(".lintfix/plan.json", ".lintfix/optimize.json", ".lintfix/metrics.json"),
        exit_codes=(
            (0, "plan written, or apply verified"),
            (1, "apply or verifier failed"),
            _NO_PYPROJECT,
        ),
        flags=(
            FlagSpec("--mutation-budget=", "value", "", "named or numeric mutation budget"),
            FlagSpec("--budget=", "value", "unblock", "named budget profile"),
            FlagSpec("--base=", "value", "origin/main", "git ref to diff against"),
            FlagSpec("--stats=", "value", "", "path to replay stats JSON"),
            FlagSpec("--verify-cmd=", "value", "", "command used to verify an apply"),
            FlagSpec("--renovate", "boolean", "off", "use the broad-cleanup renovation profile"),
            FlagSpec("--apply", "boolean", "off", "mutate source instead of planning"),
            FlagSpec("--annotate", "boolean", "off", "emit GitHub Actions annotations"),
            FlagSpec("--metrics", "boolean", "off", "write .lintfix/metrics.json"),
            FlagSpec("--no-stats", "boolean", "off", "skip reading replay stats"),
            FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),
        ),
    ),
    CommandDoc(
        "fix-annotate",
        "Emit GitHub Actions annotations from .lintfix/plan.json (advisory; never fails CI)",
        "Surface fix-plan findings as PR annotations in a CI step; advisory only.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "annotations emitted (advisory; never fails CI)"),
            (2, "malformed plan JSON"),
        ),
        flags=(
            FlagSpec("--input=", "value", "", "path to the plan JSON to annotate"),
            FlagSpec("--source=", "value", "plan", "which .lintfix/ artifact to read"),
            FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),
        ),
    ),
    CommandDoc(
        "fix-metrics",
        "Aggregate .lintfix/{plan,optimize,replay}.json into .lintfix/metrics.json",
        "Roll the standalone .lintfix/ artifacts into one metrics file for CI reporting.",
        mutates=False,
        outputs=(".lintfix/metrics.json",),
        exit_codes=(
            (0, "metrics written"),
            (1, "aggregation failed"),
            _NO_PYPROJECT,
        ),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
    ),
    CommandDoc(
        "format",
        "Format code with ruff",
        "Run after edits to apply ruff formatting; mutates source in place.",
        mutates=True,
        outputs=(),
        exit_codes=(
            (0, "formatting applied cleanly"),
            (1, "ruff reported an error"),
            _NO_PYPROJECT,
        ),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
    ),
    CommandDoc(
        "format-check",
        "Check formatting with ruff (read-only)",
        "Read-only formatting check for CI parity or to inspect drift without mutating source.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "formatting clean"),
            (1, "formatting drift found"),
            _NO_PYPROJECT,
        ),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
    ),
    CommandDoc(
        "lint",
        "Lint code with ruff (read-only)",
        "Read-only lint check for CI or to inspect violations without mutating source.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "no violations"),
            (1, "violations found"),
            _NO_PYPROJECT,
        ),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
    ),
    CommandDoc(
        "typecheck",
        "Type-check with basedpyright",
        "Run to catch type errors; read-only.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "no type errors"),
            (1, "type errors found"),
            _NO_PYPROJECT,
        ),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
    ),
    CommandDoc(
        "test",
        "Run tests (auto-detects pytest vs unittest)",
        "Run the project test suite; runner is auto-detected.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "all tests passed"),
            (1, "a test failed"),
            _NO_PYPROJECT,
        ),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
    ),
    CommandDoc(
        "audit",
        "Audit dependencies for known vulnerabilities",
        "Scan installed dependencies for known CVEs via pip-audit; needs network access.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "no known vulnerabilities"),
            (1, "vulnerabilities found"),
            _NO_PYPROJECT,
        ),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
    ),
    CommandDoc(
        "deps",
        "Dep hygiene: unused/missing/transitive (deptry)",
        "Check for unused, missing, or transitively-imported dependencies via deptry.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "dependency hygiene clean"),
            (1, "unused/missing/transitive issues found"),
            _NO_PYPROJECT,
        ),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
    ),
    CommandDoc(
        "deps-freshness",
        "Check outdated dependencies via explicit package-index lookup",
        "Explicitly check for outdated dependencies; not part of default PR CI, "
        "needs network access.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "all dependencies current"),
            (1, "outdated dependencies found"),
            _NO_PYPROJECT,
        ),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
    ),
    CommandDoc(
        "arch",
        "Architectural contracts (import-linter; default: src ↛ tests)",
        "Enforce import-layering contracts; the default contract forbids source importing tests.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "contracts hold"),
            (1, "a contract was violated"),
            _NO_PYPROJECT,
        ),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
    ),
    CommandDoc(
        "acceptance",
        "Gherkin acceptance tests (pytest-bdd default; behave auto-detected)",
        "Run Gherkin acceptance scenarios; runner auto-detected between pytest-bdd and behave.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "all scenarios passed"),
            (1, "a scenario failed"),
            _NO_PYPROJECT,
        ),
        flags=(
            FlagSpec(
                "--trace",
                "boolean",
                "off",
                "collect advisory runtime public-symbol trace evidence",
            ),
            FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),
        ),
    ),
    CommandDoc(
        "behavior-attribution",
        "Verify BDD scenarios reach symbols declared by claimed behaviors",
        "Verify that BDD scenarios claiming a behavior actually exercise its "
        "declared public symbols; blocking only when enforcement is enabled.",
        mutates=False,
        outputs=(".interlocks/behavior-attribution.json",),
        exit_codes=(
            (0, "all claimed behaviors reached, or advisory"),
            (1, "attribution failed and enforcement is on"),
            _NO_PYPROJECT,
        ),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
    ),
    CommandDoc(
        "init-acceptance",
        "Scaffold tests/features + tests/step_defs (pytest-bdd layout)",
        "Scaffold a working pytest-bdd acceptance example; preserves existing files "
        "and creates missing scaffold files.",
        mutates=True,
        outputs=("tests/features/", "tests/step_defs/"),
        exit_codes=(
            (0, "scaffold present"),
            _NO_PYPROJECT,
        ),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
    ),
    CommandDoc(
        "properties",
        "Property tests via pytest + Hypothesis profiles",
        "Run generated-input property tests; use `init-properties` to scaffold "
        "them, `--profile=check` for local edits, and `--profile=ci|nightly` "
        "for deeper sweeps. Skips cleanly when no property tests are present.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "all property tests passed, or no property tests were present"),
            (1, "a property test failed or the selected profile is invalid"),
            _NO_PYPROJECT,
        ),
        flags=(
            FlagSpec(
                "--profile=",
                "value",
                "ci",
                "Hypothesis profile: check, ci, nightly, default",
            ),
            FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),
        ),
    ),
    CommandDoc(
        "init-properties",
        "Scaffold the configured property-test dir",
        "Create a replaceable example in the configured property-test directory "
        "when no domain property tests exist; defaults to root-level properties/, "
        "preserves existing files, and no-ops once domain properties are present.",
        mutates=True,
        outputs=("<properties_dir>/test_example_properties.py (when needed)",),
        exit_codes=(
            (0, "scaffold written, or domain property tests already present"),
            _NO_PYPROJECT,
        ),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
        mutates_note="creates scaffold only when no domain property tests exist",
    ),
    CommandDoc(
        "coverage",
        "Tests with coverage threshold (--min=N, optional properties)",
        "Run tests under coverage.py and enforce a fail-under threshold; `--min=N` "
        "overrides the configured `coverage_min`. Pass `--properties[=profile]` "
        "to append property tests before the coverage report.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "coverage at or above threshold"),
            (1, "coverage below threshold"),
            _NO_PYPROJECT,
        ),
        flags=(
            FlagSpec("--min=", "value", "cfg.coverage_min", "coverage fail-under percentage"),
            FlagSpec(
                "--properties",
                "optional",
                "off",
                "append property tests before reporting (profile default: ci)",
            ),
            FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),
        ),
    ),
    CommandDoc(
        "complexity",
        "Complexity gate via lizard",
        "Run the same static complexity threshold check used by `interlocks ci`.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "all functions are within configured complexity thresholds"),
            (1, "one or more functions exceeded a complexity threshold"),
            _NO_PYPROJECT,
        ),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
    ),
    CommandDoc(
        "crap",
        "CRAP complexity x coverage gate",
        "Catch complex code shipped without matching tests; blocking depends on `enforce_crap`.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "no CRAP offenders"),
            (1, "offenders found and enforce_crap is on"),
            _NO_PYPROJECT,
        ),
        flags=(
            FlagSpec("--max=", "value", "cfg.crap_max", "max allowed CRAP score"),
            FlagSpec("--changed-only", "boolean", "off", "limit to files changed vs main"),
            FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),
        ),
    ),
    CommandDoc(
        "mutation",
        "Mutation testing via mutmut (advisory; see `interlocks nightly`)",
        "Catch tests that pass without actually testing the code; advisory unless "
        "`enforce_mutation` is set or `--min-score=` is passed.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "complete score at or above threshold, or advisory skip"),
            (1, "score below threshold, or enforced run timed out before completion"),
            _NO_PYPROJECT,
        ),
        flags=(
            FlagSpec(
                "--min-score=", "value", "cfg.mutation_min_score", "enforce a mutation score floor"
            ),
            FlagSpec(
                "--min-coverage=",
                "value",
                "cfg.mutation_min_coverage",
                "minimum line coverage to run mutation",
            ),
            FlagSpec(
                "--max-runtime=", "value", "cfg.mutation_max_runtime", "per-run timeout in seconds"
            ),
            FlagSpec("--changed-only", "boolean", "off", "limit to files changed vs main"),
            FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),
        ),
    ),
    # ── Stages ───────────────────────────────────────────────────────────
    CommandDoc(
        "check",
        "Local edit loop: fix/format, typecheck/tests, optional acceptance/properties",
        "The local edit loop — run after edits, before pushing; default mutation is "
        "budgeted from the author diff, strict projects can include acceptance and "
        "property tests, and `--changed` skips broad test/acceptance/property gates "
        "with follow-up next actions.",
        mutates=True,
        outputs=(),
        exit_codes=(
            (0, "all gates passed"),
            (1, "a gate failed"),
            _NO_PYPROJECT,
        ),
        flags=(
            FlagSpec(
                "--changed",
                "optional",
                "cfg.changed_ref",
                "scope file-level gates; skips test, acceptance, properties; "
                "accepts --changed=REF",
            ),
            FlagSpec("--renovate", "boolean", "off", "use the broad-cleanup renovation profile"),
            FlagSpec("--mutation-budget=", "value", "", "named or numeric mutation budget"),
            FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),
            _SKIP_FLAG,
        ),
    ),
    CommandDoc(
        "pre-commit",
        "Staged checks + tests",
        "Git pre-commit stage — applies selected budgeted lint/format candidates, "
        "re-stages changed files, then typechecks and tests; use `--renovate` for "
        "intentional broad cleanup.",
        mutates=True,
        outputs=(),
        exit_codes=(
            (0, "all gates passed"),
            (1, "a gate failed"),
            _NO_PYPROJECT,
        ),
        flags=(
            FlagSpec("--renovate", "boolean", "off", "use the broad-cleanup renovation profile"),
            FlagSpec("--mutation-budget=", "value", "", "named or numeric mutation budget"),
            FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),
            _SKIP_FLAG,
        ),
    ),
    CommandDoc(
        "ci",
        "Full verification: lint, audit, typecheck, tests, coverage, properties, CRAP",
        "The PR / protected-branch verification stage; read-only, writes timing "
        "evidence to .interlocks/ci.json.",
        mutates=False,
        outputs=(".interlocks/ci.json",),
        exit_codes=(
            (0, "all gates passed"),
            (1, "a gate failed"),
            _NO_PYPROJECT,
        ),
        flags=(
            FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),
            _SKIP_FLAG,
        ),
    ),
    CommandDoc(
        "nightly",
        "Long-running gates: coverage + properties + audit + mutation (blocking)",
        "The scheduled-job stage for slow gates; mutation always runs the full "
        "suite and blocks on `mutation_min_score`.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "all gates passed"),
            (1, "a gate failed"),
            _NO_PYPROJECT,
        ),
        flags=(
            _SKIP_FLAG,
            FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),
        ),
    ),
    CommandDoc(
        "post-edit",
        "Budgeted lint/format mutation if source files changed (Claude Code hook)",
        "Editor/agent hook interface — advisory budgeted Ruff lint/format mutation "
        "on changed Python files; skipped broad candidates are recorded in .lintfix/.",
        mutates=True,
        outputs=(),
        exit_codes=((0, "always (advisory hook; never blocks)"),),
        flags=(
            FlagSpec("--renovate", "boolean", "off", "use the broad-cleanup renovation profile"),
            FlagSpec("--mutation-budget=", "value", "", "named or numeric mutation budget"),
            FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),
            _SKIP_FLAG,
        ),
    ),
    CommandDoc(
        "setup-hooks",
        "Install git pre-commit and Claude Stop hooks",
        "Install only the git pre-commit hook and Claude Code Stop hook; use when "
        "managing agent docs and the skill separately.",
        mutates=True,
        outputs=(".git/hooks/pre-commit",),
        exit_codes=((0, "hooks installed"),),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
        mutates_note="installs or refreshes git pre-commit and Claude Stop hooks",
    ),
    CommandDoc(
        "clean",
        "Remove cache, build, coverage, and generated artifacts",
        "Remove caches, build artifacts, coverage output, mutation state, and "
        "__pycache__/ directories.",
        mutates=True,
        outputs=(),
        exit_codes=(
            (0, "artifacts removed"),
            (1, "ruff clean failed"),
            _NO_PYPROJECT,
        ),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
        mutates_note="deletes known cache/build/generated artifacts",
    ),
    # ── Reports ──────────────────────────────────────────────────────────
    CommandDoc(
        "trust",
        "Actionable trust report: coverage, CRAP, suspicious tests, next actions",
        "Get one actionable ground-truth report combining coverage, CRAP, "
        "mutation, suspicious-test inspection, and next actions; advisory.",
        mutates=False,
        outputs=(".interlocks/trust.json",),
        exit_codes=(
            (0, "report rendered (advisory; never fails)"),
            _NO_PYPROJECT,
        ),
        flags=(
            FlagSpec("--no-trend", "boolean", "off", "omit the historical trend section"),
            FlagSpec("--refresh", "boolean", "off", "recompute metrics instead of reading cache"),
            FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),
        ),
    ),
    CommandDoc(
        "evaluate",
        "Score automatable quality checklist items",
        "Score the automatable quality checklist for a 0-36 verdict without "
        "running tests, audits, or mutation; advisory.",
        mutates=False,
        outputs=(),
        exit_codes=((0, "report rendered (advisory; never fails)"),),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
    ),
    CommandDoc(
        "property-candidates",
        "Rank functions for property-test hardening",
        "Static, agent-readable report that ranks source functions likely to "
        "benefit from generated-input property tests; use `--changed=REF` to "
        "scope the next pass, `--uncovered` to hide already referenced units, "
        "and `--max-refs=N` to find shallowly referenced units. "
        "It writes no tests.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "candidate report rendered"),
            _NO_PYPROJECT,
        ),
        flags=(
            FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),
            FlagSpec(
                "--changed",
                "optional",
                "cfg.changed_ref",
                "scope to git-changed files; accepts --changed=REF",
            ),
            FlagSpec(
                "--uncovered",
                "boolean",
                "off",
                "hide candidates already referenced by property tests",
            ),
            FlagSpec(
                "--max-refs=",
                "value",
                "",
                "show only candidates with at most N property-test references",
            ),
            FlagSpec("--limit=", "value", "20", "maximum candidates to show; 0 means all"),
        ),
    ),
    CommandDoc(
        "explain",
        "Explain what each command does, in prose",
        "Learn the whole CLI contract in one call, or pass a command name for one "
        "command's prose block; read-only, works with no pyproject.toml.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "explanation printed"),
            (1, "unknown command or unexpected option"),
        ),
        flags=(
            FlagSpec("--all", "boolean", "off", "render every command's full prose block"),
            FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),
        ),
        usage="explain [--all | <command>]",
    ),
    # ── Utility ──────────────────────────────────────────────────────────
    CommandDoc(
        "config",
        "Show all [tool.interlocks] keys with defaults, current values, and sources",
        "The single source of truth for agents driving setup — lists every "
        "[tool.interlocks] key with type, default, current value, source, and description.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "reference printed"),
            (1, "invalid arguments"),
        ),
        flags=(
            FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),
            FlagSpec(
                "--bundled-only",
                "boolean",
                "off",
                "show only the bundled tool config (config show)",
            ),
        ),
        usage="config [show <tool> [--bundled-only] [--json]]",
    ),
    CommandDoc(
        "doctor",
        "Preflight diagnostic: paths, tools, venv",
        "Diagnose a project before running gates — detected paths, tools, venv, "
        "blockers, and next steps; runs no gates, exempt from the pyproject preflight.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "advisory — no blockers, or blocked without --strict"),
            (1, "pyproject.toml unreadable"),
            (2, "blocked, with --strict"),
        ),
        flags=(
            FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),
            FlagSpec("--strict", "boolean", "off", "exit non-zero when blocked"),
        ),
    ),
    CommandDoc(
        "setup",
        "Install/check hooks, agent docs, and Claude skill",
        "The recommended one-command local onboarding — installs hooks, agent docs, "
        "and the Claude skill; `--check` verifies them read-only.",
        mutates=True,
        outputs=(
            ".git/hooks/pre-commit",
            ".claude/skills/interlocks/SKILL.md",
            "AGENTS.md or CLAUDE.md",
        ),
        exit_codes=(
            (0, "integrations installed or verified"),
            (1, "an integration is missing or stale (--check)"),
        ),
        flags=(
            FlagSpec("--check", "boolean", "off", "verify integrations read-only"),
            FlagSpec("--ci=", "value", "", "install a CI workflow (github)"),
            FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),
        ),
        usage="setup [--check] [--ci=github] [--json]",
        mutates_note="yes; --check is read-only",
    ),
    CommandDoc(
        "init",
        "Scaffold a greenfield pyproject.toml + tests/ in CWD",
        "Bootstrap a greenfield project — writes pyproject.toml and a tests/ "
        "smoke test; preserves existing test scaffold files but refuses to overwrite "
        "an existing pyproject.toml.",
        mutates=True,
        outputs=("pyproject.toml", "tests/__init__.py", "tests/test_smoke.py"),
        exit_codes=(
            (0, "project scaffold present"),
            (1, "pyproject.toml already exists"),
        ),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
    ),
    CommandDoc(
        "agents",
        "Register interlocks block in AGENTS.md / CLAUDE.md (idempotent)",
        "Append or create the interlocks guidance block in AGENTS.md / CLAUDE.md; idempotent.",
        mutates=True,
        outputs=("AGENTS.md or CLAUDE.md",),
        exit_codes=((0, "block registered"),),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
        mutates_note="creates or appends only docs missing check-stage guidance",
    ),
    CommandDoc(
        "setup-skill",
        "Install bundled Claude Code SKILL.md (idempotent)",
        "Install or refresh the bundled Claude Code skill at "
        ".claude/skills/interlocks/SKILL.md; idempotent.",
        mutates=True,
        outputs=(".claude/skills/interlocks/SKILL.md",),
        exit_codes=((0, "skill installed"),),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
        mutates_note="installs or refreshes the managed bundled skill file",
    ),
    CommandDoc(
        "presets",
        "Show preset options or set one with `presets set <preset>`",
        "Show preset options, current values, and copyable progressive config; "
        "listing is read-only, while `presets set <preset>` writes the preset "
        "into pyproject.toml.",
        mutates=True,
        outputs=("pyproject.toml",),
        exit_codes=(
            (0, "options shown, or preset set"),
            (1, "invalid preset or usage"),
        ),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
        usage="presets [set <preset>]",
        mutates_note="listing is read-only; set writes pyproject.toml",
    ),
    CommandDoc(
        "baseline",
        "Read/init/advance the progressive-preset quality floor (`show|init|advance|check`)",
        "Read, initialize, advance, or check the progressive-preset quality floor "
        "stored in .interlocks/baseline.json; `show`/`check` are read-only, "
        "while `init`/`advance` write the floor.",
        mutates=True,
        outputs=(".interlocks/baseline.json (init/advance)",),
        exit_codes=(
            (0, "succeeded, or check passed"),
            (1, "check found a regression"),
            _NO_PYPROJECT,
        ),
        flags=(
            FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),
            FlagSpec("--auto-pr", "boolean", "off", "open a PR when advancing the baseline"),
        ),
        usage="baseline [show|init|advance|check] [--json] [--auto-pr]",
        mutates_note="show/check are read-only; init/advance write baseline.json",
    ),
    CommandDoc(
        "version",
        "print interlocks version",
        "Print the installed interlocks version.",
        mutates=False,
        outputs=(),
        exit_codes=((0, "version printed"),),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
    ),
    CommandDoc(
        "warm",
        "Pre-fetch bundled tool wheels into ~/.cache/uv (for offline runs)",
        "Pre-fetch bundled tool wheels into ~/.cache/uv so later runs work with UV_OFFLINE=1.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "wheels cached"),
            (1, "a wheel failed to fetch or verify"),
        ),
        flags=(FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),),
    ),
    # ── Other ────────────────────────────────────────────────────────────
    CommandDoc(
        "help",
        "Show this help message",
        "Show the command list plus detected paths, active preset, and thresholds; "
        "`help --advanced` lists every subcommand.",
        mutates=False,
        outputs=(),
        exit_codes=((0, "help printed"),),
        flags=(
            FlagSpec("--advanced", "boolean", "off", "list every command"),
            FlagSpec("--json", "boolean", "off", "emit machine-readable JSON"),
        ),
        usage="help [--advanced | <command>]",
    ),
)


COMMAND_DOCS_BY_NAME: dict[str, CommandDoc] = {doc.name: doc for doc in COMMAND_DOCS}

COMMAND_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Tasks",
        (
            "fix",
            "fix-rule",
            "fix-plan",
            "fix-replay",
            "fix-optimize",
            "fix-annotate",
            "fix-metrics",
            "format",
            "format-check",
            "lint",
            "typecheck",
            "test",
            "audit",
            "deps",
            "deps-freshness",
            "arch",
            "acceptance",
            "behavior-attribution",
            "init-acceptance",
            "properties",
            "init-properties",
            "coverage",
            "complexity",
            "crap",
            "mutation",
        ),
    ),
    (
        "Stages",
        ("check", "pre-commit", "ci", "nightly", "post-edit", "setup-hooks", "clean"),
    ),
    ("Reports", ("trust", "evaluate", "property-candidates", "explain")),
    (
        "Utility",
        (
            "config",
            "doctor",
            "setup",
            "init",
            "agents",
            "setup-skill",
            "presets",
            "baseline",
            "version",
            "warm",
        ),
    ),
    ("Other", ("help",)),
)


# Dispatcher-level tokens that are valid on every command and must never be
# matched against a task's declared FlagSpec set. Command-specific help flags
# such as `help --advanced` stay documented on that command. `--skip` carries a
# value and needs a prefix check; it is handled separately in `unknown_task_flags`.
GLOBAL_FLAGS: frozenset[str] = frozenset({"--help", "-h", "--verbose", "--quiet"})


def unknown_task_flags(task_name: str, raw_args: list[str]) -> list[str]:
    """Return the ``-*`` tokens in ``raw_args`` that ``task_name`` does not accept.

    A token is accepted when it is a global/dispatcher-level flag
    (:data:`GLOBAL_FLAGS` or a ``--skip`` / ``--skip=…`` token), or when it
    matches a declared :class:`FlagSpec` for the task. Value flags
    (``FlagSpec.name`` ends with ``=``) match a ``--flag=value`` token by
    prefix; optional flags match either ``--flag`` or ``--flag=value``; boolean
    flags match only the bare token. The first positional token (the task name
    itself) is ignored — it never starts with ``-``.
    """
    boolean_names, optional_names, value_prefixes = _flag_sets_for_task(task_name)
    bad: list[str] = []
    for arg in raw_args:
        if _unknown_flag(arg, boolean_names, optional_names, value_prefixes):
            bad.append(arg)
    return bad


def _flag_sets_for_task(
    task_name: str,
) -> tuple[frozenset[str], frozenset[str], tuple[str, ...]]:
    doc = COMMAND_DOCS_BY_NAME.get(task_name)
    declared = doc.flags if doc is not None else ()
    return (
        frozenset(
            spec.name
            for spec in declared
            if spec.kind == "boolean" and not spec.name.endswith("=")
        ),
        frozenset(spec.name for spec in declared if spec.kind == "optional"),
        tuple(spec.name for spec in declared if spec.name.endswith("=")),
    )


def _unknown_flag(
    arg: str,
    boolean_names: frozenset[str],
    optional_names: frozenset[str],
    value_prefixes: tuple[str, ...],
) -> bool:
    if not arg.startswith("-"):
        return False
    if arg in GLOBAL_FLAGS:
        return False
    if arg == "--skip" or arg.startswith("--skip="):
        return False
    if arg in boolean_names or arg in optional_names:
        return False
    if arg.split("=", 1)[0] in optional_names:
        return False
    return not any(arg.startswith(prefix) for prefix in value_prefixes)
