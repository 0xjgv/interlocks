# Repository Guidelines

## Project Structure & Module Organization
- Core package code lives in `harness/`, with CLI entrypoints in `harness/cli.py`, shared runner logic in `harness/runner.py`, stage helpers in `harness/stages/`, and task commands in `harness/tasks/`.
- Tests live in `tests/` and currently use small `unittest` smoke checks.
- Project metadata and tool configuration are centralized in `pyproject.toml`; lockfile state is in `uv.lock`.

## Build, Test, and Development Commands
- `uv run harness check` — local post-edit workflow: fix, format, typecheck, test, and suppression report.
- `uv run harness ci` — read-only CI suite: lint, format check, typecheck, dep hygiene (deptry), complexity gate, architectural contracts (import-linter, when expressible), and tests with coverage.
- `uv run harness pre-commit` — run the staged-file checks used by the git hook.
- `uv run harness setup-hooks` — install the repository git hook.
- `uv run python -m unittest discover -s tests` — direct test run when iterating on Python code.

## Coding Style & Naming Conventions
- Target Python `3.13` and follow the existing Ruff configuration (`line-length = 99`).
- Use 4-space indentation, explicit type hints on production code, and `snake_case` for functions/modules.
- Keep task commands named `cmd_<task>` to match the CLI pattern already used in `harness/tasks/`.
- Let Ruff handle import ordering and formatting; do not add new tooling unless it is already part of the project.

## Testing Guidelines
- Add or update `unittest` coverage in `tests/` for every behavior change.
- Name new test files `test_<feature>.py` and test methods `test_<behavior>`.
- Before finishing code changes, run `uv run harness check`; for release/CI parity, also use `uv run harness ci`.
- Coverage is enforced via `coverage.py` with `fail_under = 80`.

## Commit & Pull Request Guidelines
- Follow the repository’s conventional style: `feat(scope): ...`, `refactor(scope): ...`, etc.
- Keep commits focused and explain the user-visible reason for the change, not just the file edits.
- PRs should summarize behavior changes, list validation performed, and mention any follow-up work or risk areas.

## Security & Configuration Tips
- Do not commit secrets, generated credentials, or machine-specific config.
- Prefer the existing `harness` commands over ad hoc shell pipelines so checks stay consistent locally and in CI.
