# Repository Guidelines

## Project Structure & Module Organization

Core package code lives in `interlocks/`. The CLI entrypoint is `interlocks/cli.py`, shared process execution is in `interlocks/runner.py`, stage orchestration is in `interlocks/stages/`, and task commands live in `interlocks/tasks/`. Bundled configuration templates and examples are stored in `interlocks/defaults/` and shipped as package data.

Tests live in `tests/`, with focused task and stage coverage under `tests/tasks/` and `tests/stages/`. BDD feature files are in `tests/features/`, with step definitions in `tests/step_defs/`. Website documentation assets live under `docs/`.

## Build, Test, and Development Commands

- `uv run interlocks check` - primary post-edit workflow: fix, format, typecheck, tests, suppressions report, and cached CRAP advisory.
- `uv run interlocks warm` - pre-fetch the bundled tool wheels (`interlocks/defaults/tools.py`) into `~/.cache/uv` so subsequent runs work under `UV_OFFLINE=1`. From 0.2.0 the wheel ships zero runtime deps and dispatches every gate through `uvx` / `uv run --with`.
- `uv run interlocks ci` - CI parity suite: format-check, lint, complexity, audit (warn-skip on network), deps, typecheck, coverage, arch, acceptance, CRAP, optional mutation per `mutation_ci_mode`. Writes `.interlocks/ci.json` timing evidence and coverage artifacts.
- `uv run interlocks nightly` - long-running gates: coverage, audit, mutation (blocking on `mutation_min_score`).
- `uv run interlocks pre-commit` - staged-file checks used by the git hook.
- `uv run interlocks setup` - installs or refreshes local hooks, agent docs, and bundled Claude skill.
- `uv run interlocks setup --check` - verifies local integrations without writing.
- `uv run interlocks setup --ci=github` - installs a GitHub Actions workflow only when no existing workflow invokes interlocks.
- `uv run interlocks setup --ci=github --check` - verifies GitHub CI wiring read-only.
- `uv run interlocks doctor` - readiness diagnostic; static inspection only.
- `uv run interlocks evaluate` - read-only 11-check quality scorecard (0–33).
- `uv run interlocks help` / `interlocks config` / `interlocks presets` - resolved thresholds, full config key list, preset selector.
- `uv run pytest -q` - direct repository test run, including this repo's pytest-bdd acceptance tests.

## Coding Style & Naming Conventions

Target Python `3.11+`. Use 4-space indentation, explicit type hints in production code, and `snake_case` for modules, functions, and variables. Keep task commands named `cmd_<task>` to match CLI dispatch.

Ruff owns linting, import ordering, and formatting. Line length is `99`; first-party imports are `interlocks`. Avoid adding new tools unless already represented in `pyproject.toml`.

## Testing Guidelines

Add or update tests for every behavior change. Use `test_<feature>.py` filenames and `test_<behavior>` test methods or functions. Prefer focused unit tests; add BDD coverage for CLI-level behavior or user workflows.

Coverage is measured with `coverage.py`, branch coverage is enabled, and `fail_under = 80`. Before finishing code changes, run `uv run interlocks check`; use `uv run interlocks ci` when release or CI parity matters.

## Commit & Pull Request Guidelines

Git history follows Conventional Commits, for example `feat(website): docs content` and `chore(v1.0): consolidate release history`. Keep commits focused and describe the user-visible reason for the change.

Pull requests should summarize behavior changes, list validation performed, and call out risks or follow-up work. Link issues when applicable. Include screenshots only for website or visual documentation changes.

## Security & Configuration Tips

Do not commit secrets, generated credentials, or machine-specific configuration. Prefer the repository’s `interlocks` commands over ad hoc tool invocations so local checks stay aligned with CI.
