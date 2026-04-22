# CLAUDE

## Install

- `pipx install pyharness` (or `uv tool install pyharness` for uv users). All tools ship with the CLI.

## Commands

- After edits: `harness check` — fix, format, typecheck, test, suppression report
- Pre-commit: `harness pre-commit` — staged files only (auto via git hook)
- CI: `harness ci` — read-only lint, format check, typecheck, dep hygiene, complexity gate (lizard, CCN 15), tests with coverage
- Audit: `harness audit` — audit dependencies for known vulnerabilities (via pip-audit)
- Deps: `harness deps` — dependency hygiene (unused/missing/transitive) via deptry; auto-passes `--known-first-party` from `src_dir`. Override with `[tool.deptry]` in pyproject.
- Arch: `harness arch` — architectural contracts via import-linter. Uses `[tool.importlinter]` when present; otherwise runs a default contract forbidding `src_dir` from importing `test_dir`. Skips with a nudge if `test_dir` isn't a Python package.
- Coverage: `harness coverage --min=0` — coverage.py with threshold + uncovered listing
- CRAP (advisory): `harness crap --max=30` — complexity × coverage gate
- Mutation (advisory): `harness mutation --min-coverage=70 --max-runtime=600` — mutmut
- Setup: `harness setup-hooks` to install git pre-commit hook
- Auto-format: runs automatically after Claude edits via `Stop` hook (post-edit)

## Context

- This project is a CLI tool for managing Python projects (we use it internally to dogfood the tool).

## Configuration

`harness` walks up from CWD to find the nearest `pyproject.toml` (pytest-style rootdir) and auto-detects source/test dirs, test runner, and invoker. All keys under `[tool.harness]` are optional overrides:

```toml
[tool.harness]
src_dir = "harness"       # auto: src/<pkg>, top-level pkg, or [tool.uv.build-backend]
test_dir = "tests"        # auto: first existing of tests/, test/, src/tests/
test_runner = "pytest"    # "pytest" | "unittest" — auto from pytest config/deps/import
test_invoker = "python"   # "python" | "uv" — auto "uv" when uv.lock present
pytest_args = ["-q"]      # extra args appended to pytest commands
```

- `harness help` prints the detected values — a quick sanity check in any repo.
