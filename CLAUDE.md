# CLAUDE

## Install

- `pipx install interlocks` (or `uv tool install interlocks` for uv users). All tools ship with the CLI.

## Commands

- After edits: `interlocks check` — fix, format, typecheck, test, suppression report
- Pre-commit: `interlocks pre-commit` — staged files only (auto via git hook)
- CI: `interlocks ci` — read-only lint, format check, typecheck, dep hygiene, complexity gate (lizard, CCN 15), tests with coverage, blocking CRAP gate (`enforce_crap = false` to opt out; `run_mutation_in_ci = true` to add mutation)
- Nightly: `interlocks nightly` — long-running gates (coverage + mutation, blocking on `mutation_min_score`); schedule via cron/GitHub Actions
- Audit: `interlocks audit` — audit dependencies for known vulnerabilities (via pip-audit); `audit_severity_threshold` makes severity policy visible to `evaluate`
- Deps: `interlocks deps` — dependency hygiene (unused/missing/transitive) via deptry; auto-passes `--known-first-party` from `src_dir`. Override with `[tool.deptry]` in pyproject.
- Deps freshness: `interlocks deps-freshness` — explicit package-index freshness check (not in default PR CI); `evaluate_dependency_freshness = true` makes policy count in `evaluate`
- Arch: `interlocks arch` — architectural contracts via import-linter. Uses `[tool.importlinter]` when present; otherwise runs a default contract forbidding `src_dir` from importing `test_dir`. Skips with a nudge if `test_dir` isn't a Python package.
- Acceptance: `interlocks acceptance` — Gherkin scenarios via pytest-bdd (default, shares coverage with `test`). Falls back to behave when `features/steps/` + `features/environment.py` are present or `acceptance_runner = "behave"`. No-ops silently when no `features/` directory exists. `run_acceptance_in_check = true` opts the `check` stage into running it. Blocking in `ci`; when `require_acceptance = true`, registered public behavior IDs need `# req:` or `@req-*` scenario markers. `INTERLOCKS_ACCEPTANCE_TRACE=1` enables advisory trace evidence only.
- Scaffold: `interlocks init-acceptance` — writes `tests/features/example.feature`, `tests/step_defs/test_example.py`, `tests/step_defs/conftest.py`. Refuses to overwrite.
- Coverage: `interlocks coverage --min=0` — coverage.py with threshold + uncovered listing
- CRAP: `interlocks crap --max=30` — complexity × coverage gate (blocking by default; `enforce_crap = false` to stay advisory)
- Mutation: `interlocks mutation --min-coverage=70 --max-runtime=600` — mutmut (advisory unless `enforce_mutation = true` or `--min-score=` is set; see `interlocks nightly`)
- Trust: `interlocks trust` — trust-score report (verdict + suspicious tests + hot files), read-only; `--refresh` re-runs coverage first, `--verbose` for full breakdown, `--no-trend` to skip the `.interlocks/trust.json` cache
- Config: `interlocks config` — list every `[tool.interlocks]` key with type, default, description, and current resolved value (read-only)
- Setup: `interlocks setup-hooks` to install git pre-commit hook
- Auto-format: runs automatically after Claude edits via `Stop` hook (post-edit)

## Context

- This project is a CLI tool for managing Python projects (we use it internally to dogfood the tool).
- Acceptance is self-dogfooded: `tests/features/interlock_cli.feature` + `tests/step_defs/` guard the public CLI surface via pytest-bdd.

## Configuration

`interlocks` walks up from CWD to find the nearest `pyproject.toml` (pytest-style rootdir) and auto-detects source/test dirs, test runner, and invoker. All keys under `[tool.interlocks]` are optional overrides:

```toml
[tool.interlocks]
# Paths / runners
src_dir = "interlocks"            # auto: src/<pkg>, top-level pkg, or [tool.uv.build-backend]
test_dir = "tests"             # auto: first existing of tests/, test/, src/tests/
test_runner = "pytest"         # "pytest" | "unittest" — auto from pytest config/deps/import
test_invoker = "python"        # "python" | "uv" — auto "uv" when uv.lock present
pytest_args = ["-q"]           # extra args appended to pytest commands

# Thresholds — single source of truth for every gate
coverage_min = 80              # `coverage` fail-under
crap_max = 30.0                # `crap` CRAP ceiling
complexity_max_ccn = 15        # lizard CCN cap
complexity_max_args = 7        # lizard argument count cap
complexity_max_loc = 100       # lizard LOC cap
mutation_min_coverage = 70.0   # `mutation` skip when suite coverage is lower
mutation_max_runtime = 600     # `mutation` seconds before SIGTERM
mutation_min_score = 80.0      # kill ratio (%) enforced when blocking

# Gate enforcement — flip the "fake-confidence detectors" on/off
enforce_crap = true            # CRAP exits 1 on offenders (set false to stay advisory)
run_mutation_in_ci = false     # include mutation in `interlocks ci`
enforce_mutation = false       # mutation exits 1 when score < mutation_min_score

# Acceptance (Gherkin) — all optional
acceptance_runner = "pytest-bdd" # "pytest-bdd" | "behave" | "off" (auto if unset)
features_dir = "tests/features"  # auto: tests/features/, features/, <test_dir>/features/
run_acceptance_in_check = false  # true → run scenarios inside `interlocks check`
require_acceptance = false       # true → fail stages when no Gherkin scenarios or required behavior markers are present

# Evaluation policy / cached evidence
evaluate_dependency_freshness = false        # true → score explicit freshness policy
dependency_freshness_command = "interlocks deps-freshness"
dependency_freshness_stage = "interlocks nightly"
audit_severity_threshold = "high"           # low|medium|high|critical
pr_ci_runtime_budget_seconds = 0             # 0 disables PR speed scoring
pr_ci_evidence_max_age_hours = 24
ci_evidence_path = ".interlocks/ci.json"
```

- `interlocks help` prints detected paths + resolved thresholds.

### Precedence cascade

Highest wins:

1. CLI flags (`--min=`, `--max=`, `--max-runtime=`, …)
2. Project `[tool.interlocks]` in the nearest `pyproject.toml`
3. Bundled defaults (above) + bundled tool configs under `interlocks/defaults/` — `ruff.toml`, `pyrightconfig.json`, `coveragerc`, `importlinter_template.ini`

When a target project declares its own `[tool.<tool>]` (or a sidecar like `ruff.toml`/`.coveragerc`/`pyrightconfig.json`/`.importlinter`), the bundled default is skipped and the project's config applies directly.
