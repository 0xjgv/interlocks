# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-05-08

### Breaking

- **Install model changed**: interlocks no longer ships any runtime
  dependencies. The published wheel is a thin dispatcher that invokes every
  CLI tool (`ruff`, `basedpyright`, `coverage`, `mutmut`, `deptry`,
  `import-linter`, `lizard`, `pip-audit`) through `uvx` or `uv run --with` at
  pinned versions baked into the package. **Install via `uv tool install
  interlocks` or `pipx install interlocks`** — using `uv add --group dev
  interlocks` no longer pulls the gate tools into your project resolver.
  Adding interlocks to `[project].dependencies` still works, but its zero
  declared deps mean the gates won't be available at import time without
  going through the dispatcher. **Migration**: replace any `uv add` /
  `requirements.txt` entry for interlocks with `uv tool install interlocks`.
- The `0xjgv/interlocks@v1` GitHub action now installs through
  `uv tool install`, restores `~/.cache/uv` via `actions/cache@v4`, runs
  `interlocks warm`, and executes the CI command with `UV_OFFLINE=1`. Override
  the `install-command` input if you need a different install vector — but
  `pip install interlocks` no longer brings the toolchain with it.
- Crash payload schema bumped to `2`: adds `uv_version` and `uvx_version`
  fields. Older readers must accept the additional keys or upgrade.

### Added

- `interlocks warm` pre-fetches the bundled tool wheels into `~/.cache/uv`
  so subsequent runs work under `UV_OFFLINE=1`. When the release-shipped
  `interlocks/defaults/tools.txt` (hash-pinned via `uv pip compile
  --generate-hashes`) is present, warming verifies wheels with
  `--require-hashes`; otherwise it falls back to per-tool uvx probes.
- `[tool.interlocks.tools]` table override: pin individual tools (e.g.
  `ruff = "0.14.0"`) without forking the package. Resolution chain mirrors
  the threshold resolver — CLI flag > project table > bundled default.
- `interlocks/defaults/tools.py` exposes `DEFAULTS` and `default_pin(name)`
  as the single source of truth for tool versions.
- New runner helpers: `uvx_tool(package, *args, version=, entrypoint=)` for
  stateless analyzers and `uv_run_with(package, *args, version=)` for tools
  that must share the user's interpreter (coverage.py, mutmut). Both pass
  `--index-strategy first-index` to defend against dependency confusion.
- Bundled CI workflows (`ci.yml`, `nightly.yml`, `release.yml`) restore
  `~/.cache/uv` from `actions/cache@v4` keyed on `hashFiles` of
  `interlocks/defaults/tools.{py,txt}`, run `interlocks warm`, and execute
  gates with `UV_OFFLINE=1`.

### Changed

- `[project].dependencies = []` — interlocks itself declares no Python
  package dependencies. The wheel is ~40 KB of dispatch code plus bundled
  configs.
- `audit` no longer self-forks pip-audit through interlocks's interpreter;
  it now dispatches through `uvx pip-audit==<pin> .` like every other gate.
- `mutation` now invokes `mutmut` through `uv run --with
  interlocks-mutmut==<pin>` so it carries the user's runtime + dev deps
  rather than relying on its own interpreter to import the project.

## [0.1.7] - 2026-05-06

### Added

- Global gate skipping via `--skip=...`, `INTERLOCKS_SKIP`, and
  `[tool.interlocks] skip`, with validation for unknown labels and visible
  skipped-gate warnings.
- `interlocks config show ruff|basedpyright|coverage|import-linter` to inspect
  whether each tool is using bundled defaults or project-owned native config.
- `interlocks presets` and `interlocks presets set <preset>` for discovering and
  applying adoption presets from the CLI.
- `interlocks setup --ci=github` and `setup --ci=github --check` for explicit
  GitHub Actions workflow installation and read-only CI wiring checks.

### Changed

- Interlocks now installs on Python 3.11+ again, with bundled defaults targeting
  Python 3.11 syntax for wider adoption.
- Bundled GitHub Actions wiring now uses current Node 24-compatible action
  versions.

### Fixed

- `interlocks typecheck` now resolves imports from a non-uv target project's
  in-tree `.venv` when Interlocks is run from an isolated install such as `uvx`.
- `interlocks check --changed` now works in projects without `pyproject.toml`.
- `interlocks check --changed` now includes changed Python files in flat-layout
  projects.
- Bundled basedpyright defaults now report deprecated API usage as an error.
- The `import-linter` dependency is bounded below releases that require
  `grimp` versions without macOS Python 3.11 wheels, keeping CI installs
  wheel-based on supported macOS runners.

## [0.1.6] - 2026-05-04

### Added

- `interlocks check --changed[=<ref>]` — progressive-adoption mode that scopes
  file-level gates (fix/format/typecheck/CRAP) to `.py` files changed vs
  `<ref>` (default `cfg.changed_ref` = `origin/main`). Graph-wide gates
  (deps, behavior-attribution, acceptance) and the test suite skip with a
  banner; run `interlocks test` separately for the full suite.
- `[tool.interlocks] changed_ref` — base ref used by `check --changed` when
  invoked without an explicit value.

## [0.1.5] - 2026-05-03

### Changed

- Crash reporting now prompts interactively before opening a pre-filled GitHub
  issue URL, replacing the previous environment-variable consent switch.
- Crash handling documentation and acceptance coverage now describe the
  prompt-first flow and declined-report local file behavior.

## [0.1.4] - 2026-05-01

### Added

- `interlocks behavior-attribution` — acceptance-time gate that traces
  public-symbol calls during pytest-bdd / behave runs and verifies each
  Gherkin scenario actually exercises the public symbol claimed by its
  `# req: <id>` registry entry. Stale, missing, or misattributed
  attributions fail with actionable remediation.
- `interlocks <cmd> --help` (and `-h`) — prints command-specific usage
  without running the gate.

### Changed

- `coverage` — uv-managed projects no longer need `coverage` as a project
  dependency; Interlocks injects `coverage>=7.13.5` via `uv run --with`.
  Non-uv projects get a clear preflight error when `coverage` isn't
  importable in the target Python environment.
- Test-runner detection no longer probes `pytest` importability in the
  current interpreter; only `[tool.pytest.*]` / `pytest.ini` /
  `pytest.cfg` / `<test_dir>/conftest.py` and declared deps are
  considered.
- `interlocks setup` / `setup --check` — agent-doc detection now requires
  the doc to mention `interlocks check` (or `il check`), not just the
  substring `interlocks`. Stale hand-written references no longer count
  as installed and are refreshed on `setup`.

### Fixed

- Failure dumps now name the actual failed pre-command (e.g. the coverage
  preflight) rather than always printing the main `task.cmd`.

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
