# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.3] - 2026-04-29

### Added

- `interlocks evaluate` — read-only static quality checklist scoring 8
  automatable checks (acceptance, unit-tests, coverage, mutation, complexity,
  deps, security, ci) for a 0–24 verdict with gap-closure commands and
  rationale. Preflight-exempt; runs no tests/audits/mutation/network calls.
- `interlocks deps-freshness` — explicit package-index check for outdated
  dependencies. Not in default PR CI; opt in via `evaluate_dependency_freshness`.
- `mutation_ci_mode = "off" | "incremental" | "full"` — selects how
  `interlocks ci` invokes mutmut. `incremental` restricts survivor reporting to
  files changed vs `mutation_since_ref` (default `origin/main`); `full` runs the
  whole suite; `off` (default) skips. Nightly always runs full + score gate.
- `mutation_since_ref` config key — base ref for `incremental` mutation diffs.
- `.interlocks/ci.json` — `interlocks ci` writes timing evidence consumed by
  the `evaluate` PR-speed score.
- `audit_severity_threshold`, `pr_ci_runtime_budget_seconds`,
  `pr_ci_evidence_max_age_hours`, `ci_evidence_path`,
  `evaluate_dependency_freshness`, `dependency_freshness_command`,
  `dependency_freshness_stage` config keys — make `evaluate` policy explicit.
- `require_acceptance` config key — when `true`, `interlocks ci` (and `check`
  with `run_acceptance_in_check = true`) fail when Gherkin acceptance coverage
  is missing. Default `false` preserves existing baseline/legacy behavior;
  `strict` preset enables it.
- Registered behavior coverage — public behavior IDs in
  `interlocks/behavior_coverage.py` are gated by `# req: <id>` or `@req-<id>`
  Gherkin markers under `require_acceptance = true`. Stale or duplicate
  markers fail with actionable remediation. Downstream projects with no
  registry keep zero-config behavior.
- Advisory acceptance trace evidence — `INTERLOCKS_ACCEPTANCE_TRACE=1`
  collects runtime public-symbol evidence; failures are diagnostic-only and
  do not change exit codes in this release.
- `acceptance_status` module — single source of truth for acceptance
  readiness (`disabled`, `optional_missing`, `missing_features_dir`,
  `missing_feature_files`, `missing_scenarios`, `runnable`) reused by
  `acceptance`, `ci`, `check`, and `evaluate`.

### Changed

- `interlocks ci` — runs `audit` between deps and tests with
  `allow_network_skip=True` so transient pip-audit/network failures
  warn-skip; real vulns still fail.
- `interlocks nightly` — runs `audit` between coverage and mutation with
  the same warn-skip semantics.
- Stages call `cmd_mutation(changed_only=..., min_score_default=...)`
  directly instead of mutating `sys.argv` across module boundaries.
- `mutation_ci_mode = "incremental"` now scopes `mutmut run` to module globs
  derived from files changed vs `mutation_since_ref` (default `origin/main`),
  so PR runtime scales with the diff (was: only filtered survivor display
  while mutmut still ran the full suite). Empty diff skips cleanly.
- `mutation` — live progress refresh during `mutmut run` (was: silent until
  completion). TTY-only; CI logs unchanged.

### Fixed

- `crap` — cached advisory reports stay non-blocking when `enforce_crap = false`.
- Incremental mutation diffs include staged, unstaged, and untracked Python files,
  while ignoring unrelated commits added to the base ref after branch-off.

## [0.1.2] - 2026-04-27

### Added

- `interlocks config` — list every `[tool.interlocks]` key with type, default,
  description, and current resolved value (read-only). Single source of truth
  for agents driving setup.

### Removed

- User-global `~/.config/interlocks/config.toml` config layer; configuration
  now lives only in `[tool.interlocks]`. Reason: quality gates must match
  across machines and CI.

## [0.1.1] - 2026-04-27

### Fixed

- Publish renamed `interlocks` package and CLI metadata so uvx-installed hooks invoke `interlocks.cli`.

## [0.1.0] - 2026-04-23

### Added

- Stable `interlocks <task>` CLI surface with four one-command stages:
  `check` (fix + format + typecheck + test + suppression report),
  `pre-commit` (staged-file checks + tests),
  `ci` (lint, format check, typecheck, dep hygiene, complexity, tests with coverage, blocking CRAP gate),
  `nightly` (long-running coverage + mutation gates).
- Bundled tool defaults (`ruff.toml`, `pyrightconfig.json`, `coveragerc`,
  `importlinter_template.ini`) that apply unless the target project declares
  its own `[tool.<tool>]` or sidecar config.
- Fake-confidence detectors: blocking CRAP gate (`enforce_crap`) and
  mutation testing via mutmut (`interlocks mutation`, wired into `interlocks nightly`
  with `mutation_min_score`).
- Auto-detection of `src_dir`, `test_dir`, `test_runner` (pytest/unittest),
  and `test_invoker` (python/uv) via `pyproject.toml` walk-up.
- Acceptance tests via pytest-bdd (default) or behave (auto-detected), with
  `interlocks init-acceptance` scaffold and self-dogfooded Gherkin coverage of
  the CLI surface.
- Auxiliary tasks: `interlocks audit` (pip-audit), `interlocks deps` (deptry),
  `interlocks arch` (import-linter), `interlocks coverage`, `interlocks version`.
- Git `pre-commit` and Claude Code `Stop` hook installers via
  `interlocks setup-hooks`.

### Notes

- The blocking CRAP gate is on by default (`enforce_crap = true`).
  Set `enforce_crap = false` under `[tool.interlocks]` to fall back to
  advisory mode (print offenders, exit 0).
- `interlocks mutation` stays advisory by default — mutmut runtime is
  unbounded on real codebases. Gate it per-PR with
  `run_mutation_in_ci = true` + `enforce_mutation = true`, or
  schedule `interlocks nightly` for a bounded, blocking run.
