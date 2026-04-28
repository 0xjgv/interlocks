# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `require_acceptance` config key — when set to `true`, `interlocks ci` (and
  `check` with `run_acceptance_in_check = true`) fail when Gherkin acceptance
  coverage is missing. Default `false` preserves existing baseline/legacy behavior;
  strict preset enables it.

### Changed

- `mutation_ci_mode = "incremental"` now scopes `mutmut run` to module globs
  derived from files changed vs `mutation_since_ref` (default `origin/main`),
  so PR runtime scales with the diff (was: only filtered survivor display
  while mutmut still ran the full suite). Empty diff skips cleanly.

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
