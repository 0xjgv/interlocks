# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-04-23

### Added

- Stable `harness <task>` CLI surface with four one-command stages:
  `check` (fix + format + typecheck + test + suppression report),
  `pre-commit` (staged-file checks + tests),
  `ci` (lint, format check, typecheck, dep hygiene, complexity, tests with coverage, blocking CRAP gate),
  `nightly` (long-running coverage + mutation gates).
- Bundled tool defaults (`ruff.toml`, `pyrightconfig.json`, `coveragerc`,
  `importlinter_template.ini`) that apply unless the target project declares
  its own `[tool.<tool>]` or sidecar config.
- Fake-confidence detectors: blocking CRAP gate (`enforce_crap`) and
  mutation testing via mutmut (`harness mutation`, wired into `harness nightly`
  with `mutation_min_score`).
- Auto-detection of `src_dir`, `test_dir`, `test_runner` (pytest/unittest),
  and `test_invoker` (python/uv) via `pyproject.toml` walk-up.
- Acceptance tests via pytest-bdd (default) or behave (auto-detected), with
  `harness init-acceptance` scaffold and self-dogfooded Gherkin coverage of
  the CLI surface.
- Auxiliary tasks: `harness audit` (pip-audit), `harness deps` (deptry),
  `harness arch` (import-linter), `harness coverage`, `harness version`.
- Git `pre-commit` and Claude Code `Stop` hook installers via
  `harness setup-hooks`.

### Notes

- The blocking CRAP gate is on by default (`enforce_crap = true`).
  Set `enforce_crap = false` under `[tool.harness]` to fall back to
  advisory mode (print offenders, exit 0).
- `harness mutation` stays advisory by default — mutmut runtime is
  unbounded on real codebases. Gate it per-PR with
  `run_mutation_in_ci = true` + `enforce_mutation = true`, or
  schedule `harness nightly` for a bounded, blocking run.
