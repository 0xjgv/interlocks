"""Structured documentation registry for every `interlocks` subcommand.

Pure data, stdlib only. Imports nothing from :mod:`interlocks.cli` to stay out
of the import cycle (``cli`` imports every ``cmd_*`` handler).

``CommandDoc.summary`` is the canonical one-line description; a drift-guard test
keeps the bare description string in ``cli.TASK_GROUPS`` equal to it — the same
technique used for ``CONFIG_KEYS`` vs ``ConfigKeyDoc`` in :mod:`interlocks.config`.
"""

from __future__ import annotations

from dataclasses import dataclass


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


# Lives here, not in ``cli.py``, so ``tasks/explain.py`` can resolve aliases
# without importing ``cli`` (which would create an import cycle).
ALIASES: dict[str, str] = {
    "attribution": "behavior-attribution",
    "unblock": "fix-optimize",
}


def alias_suffix(name: str) -> str:
    """Render `` (alias: x)`` / `` (aliases: x, y)`` for a canonical command name."""
    aliases = sorted(alias for alias, canonical in ALIASES.items() if canonical == name)
    if not aliases:
        return ""
    label = "alias" if len(aliases) == 1 else "aliases"
    return f" ({label}: {', '.join(aliases)})"


_NO_PYPROJECT = (2, "no pyproject.toml found")


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
    ),
    CommandDoc(
        "fix-optimize",
        "Pick the highest-value rule subset under budget; writes the full "
        ".lintfix/ set (--annotate / --metrics for CI; --apply to mutate)",
        "The self-sufficient multi-rule unblock command — discovers every fixable "
        "rule, picks the best subset under budget, and writes the full .lintfix/ set; "
        "`--apply` applies and verifies, restoring the tree on failure.",
        mutates=True,
        outputs=(".lintfix/plan.json", ".lintfix/optimize.json", ".lintfix/metrics.json"),
        exit_codes=(
            (0, "plan written, or apply verified"),
            (1, "apply or verifier failed"),
            _NO_PYPROJECT,
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
    ),
    CommandDoc(
        "init-acceptance",
        "Scaffold tests/features + tests/step_defs (pytest-bdd layout)",
        "Scaffold a working pytest-bdd acceptance example; refuses to overwrite existing files.",
        mutates=True,
        outputs=("tests/features/", "tests/step_defs/"),
        exit_codes=(
            (0, "scaffold written"),
            (1, "target files already exist"),
            _NO_PYPROJECT,
        ),
    ),
    CommandDoc(
        "coverage",
        "Tests with coverage threshold (--min=N)",
        "Run tests under coverage.py and enforce a fail-under threshold; `--min=N` "
        "overrides the configured `coverage_min`.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "coverage at or above threshold"),
            (1, "coverage below threshold"),
            _NO_PYPROJECT,
        ),
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
    ),
    CommandDoc(
        "mutation",
        "Mutation testing via mutmut (advisory; see `interlocks nightly`)",
        "Catch tests that pass without actually testing the code; advisory unless "
        "`enforce_mutation` is set or `--min-score=` is passed.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "score at or above threshold, or advisory skip"),
            (1, "score below threshold and enforce_mutation is on"),
            _NO_PYPROJECT,
        ),
    ),
    # ── Stages ───────────────────────────────────────────────────────────
    CommandDoc(
        "check",
        "Fix + format + typecheck + test (full repo)",
        "The local edit loop — run after edits, before pushing; `fix` and `format` mutate source.",
        mutates=True,
        outputs=(),
        exit_codes=(
            (0, "all gates passed"),
            (1, "a gate failed"),
            _NO_PYPROJECT,
        ),
    ),
    CommandDoc(
        "pre-commit",
        "Staged checks + tests",
        "Git pre-commit stage — fixes and formats staged Python files, re-stages, "
        "then typechecks and tests; wired automatically by the pre-commit hook.",
        mutates=True,
        outputs=(),
        exit_codes=(
            (0, "all gates passed"),
            (1, "a gate failed"),
            _NO_PYPROJECT,
        ),
    ),
    CommandDoc(
        "ci",
        "Full verification: lint, audit, typecheck, tests, coverage, CRAP",
        "The PR / protected-branch verification stage; read-only, writes timing "
        "evidence to .interlocks/ci.json.",
        mutates=False,
        outputs=(".interlocks/ci.json",),
        exit_codes=(
            (0, "all gates passed"),
            (1, "a gate failed"),
            _NO_PYPROJECT,
        ),
    ),
    CommandDoc(
        "nightly",
        "Long-running gates: coverage + mutation (blocking)",
        "The scheduled-job stage for slow gates; mutation always runs the full "
        "suite and blocks on `mutation_min_score`.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "all gates passed"),
            (1, "a gate failed"),
            _NO_PYPROJECT,
        ),
    ),
    CommandDoc(
        "post-edit",
        "Format if source files changed (Claude Code hook)",
        "Editor/agent hook interface — advisory ruff fix + format on changed "
        "Python files; never blocks.",
        mutates=True,
        outputs=(),
        exit_codes=((0, "always (advisory hook; never blocks)"),),
    ),
    CommandDoc(
        "setup-hooks",
        "Install git pre-commit and Claude Stop hooks",
        "Install only the git pre-commit hook and Claude Code Stop hook; use when "
        "managing agent docs and the skill separately.",
        mutates=True,
        outputs=(".git/hooks/pre-commit",),
        exit_codes=((0, "hooks installed"),),
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
            _NO_PYPROJECT,
        ),
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
    ),
    CommandDoc(
        "evaluate",
        "Score automatable quality checklist items",
        "Score the automatable quality checklist for a 0-33 verdict without "
        "running tests, audits, or mutation; advisory.",
        mutates=False,
        outputs=(),
        exit_codes=((0, "report rendered (advisory; never fails)"),),
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
    ),
    # ── Utility ──────────────────────────────────────────────────────────
    CommandDoc(
        "config",
        "Show all [tool.interlocks] keys with defaults and current values",
        "The single source of truth for agents driving setup — lists every "
        "[tool.interlocks] key with type, default, description, and resolved value.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "reference printed"),
            (1, "invalid arguments"),
        ),
    ),
    CommandDoc(
        "doctor",
        "Preflight diagnostic: paths, tools, venv",
        "Diagnose a project before running gates — detected paths, tools, venv, "
        "blockers, and next steps; runs no gates, exempt from the pyproject preflight.",
        mutates=False,
        outputs=(),
        exit_codes=(
            (0, "no blockers"),
            (1, "blockers present"),
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
    ),
    CommandDoc(
        "init",
        "Scaffold a greenfield pyproject.toml + tests/ in CWD",
        "Bootstrap a greenfield project — writes pyproject.toml and a tests/ "
        "smoke test; refuses to overwrite existing files.",
        mutates=True,
        outputs=("pyproject.toml", "tests/__init__.py", "tests/test_smoke.py"),
        exit_codes=(
            (0, "project scaffolded"),
            (1, "target files already exist"),
        ),
    ),
    CommandDoc(
        "agents",
        "Register interlocks block in AGENTS.md / CLAUDE.md (idempotent)",
        "Append or create the interlocks guidance block in AGENTS.md / CLAUDE.md; idempotent.",
        mutates=True,
        outputs=("AGENTS.md or CLAUDE.md",),
        exit_codes=((0, "block registered"),),
    ),
    CommandDoc(
        "setup-skill",
        "Install bundled Claude Code SKILL.md (idempotent)",
        "Install or refresh the bundled Claude Code skill at "
        ".claude/skills/interlocks/SKILL.md; idempotent.",
        mutates=True,
        outputs=(".claude/skills/interlocks/SKILL.md",),
        exit_codes=((0, "skill installed"),),
    ),
    CommandDoc(
        "presets",
        "Show preset options or set one with `presets set <preset>`",
        "Show preset options, current values, and copyable config; `presets set "
        "<preset>` writes the preset into pyproject.toml.",
        mutates=True,
        outputs=("pyproject.toml",),
        exit_codes=(
            (0, "options shown, or preset set"),
            (1, "invalid preset or usage"),
        ),
    ),
    CommandDoc(
        "baseline",
        "Read/init/advance the progressive-preset quality floor (`show|init|advance|check`)",
        "Read, initialize, advance, or check the progressive-preset quality floor "
        "stored in .interlocks/baseline.json.",
        mutates=True,
        outputs=(".interlocks/baseline.json",),
        exit_codes=(
            (0, "succeeded, or check passed"),
            (1, "check found a regression"),
            _NO_PYPROJECT,
        ),
    ),
    CommandDoc(
        "version",
        "print interlocks version",
        "Print the installed interlocks version.",
        mutates=False,
        outputs=(),
        exit_codes=((0, "version printed"),),
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
    ),
)


COMMAND_DOCS_BY_NAME: dict[str, CommandDoc] = {doc.name: doc for doc in COMMAND_DOCS}
