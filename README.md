# interlock

Adopt one Python quality loop across a repository or an organization:

```bash
pipx install interlock       # or: uv tool install interlock
cd your-python-project
interlock doctor               # readiness, detected config, blockers, next steps
interlock check                # local edit loop
interlock ci                   # CI parity
```

interlock bundles ruff, basedpyright, pytest, pytest-bdd, coverage, mutmut, deptry, import-linter, pip-audit, and lizard behind one CLI. New repositories can start with auto-detected paths and bundled tool defaults; mature repositories can opt into named presets or explicit `[tool.interlock]` thresholds when they need stronger gates.

## First-Run Adoption Loop

### 1. Install

```bash
pipx install interlock
# or
uv tool install interlock
```

Every underlying tool ships with the CLI. No per-project dev dependency list is required just to try the standard loop.

### 2. Diagnose Readiness

```bash
cd your-python-project
interlock doctor
```

`doctor` is the safe first command. It performs static local inspection only: nearest `pyproject.toml`, detected source/test/features paths, runner, invoker, active preset, resolved gate values, PATH visibility, blockers, warnings, and shortest next steps. It does not run tests, typecheck, coverage, mutation, dependency audit, or network checks.

If the repository is ready, `doctor` points you at `interlock check` and CI wiring. If it is blocked, it prioritizes the minimum setup fixes first, such as `interlock init`, missing paths, unreadable config, unsupported presets, or missing runnable tool resolution.

### 3. Run Local Checks

```bash
interlock check
```

`check` runs the local edit loop: fix, format, typecheck, tests, optional acceptance tests, advisory dependency hygiene, cached CRAP feedback when fresh coverage exists, and the suppressions report. It is the command to run after edits before pushing.

### 4. Wire CI

The direct CI command is:

```bash
interlock ci
```

For GitHub Actions, copy this workflow:

```yaml
name: interlock

on:
  pull_request:
  push:
    branches: [main]

jobs:
  interlock:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: 0xjgv/interlock@v1
```

The reusable action installs interlock, runs `interlock ci`, and writes a concise `GITHUB_STEP_SUMMARY` when GitHub provides the summary file. The action does not duplicate lint, typecheck, coverage, CRAP, dependency, architecture, acceptance, or mutation logic; the CLI remains the source of truth.

## Why This Matters for AI-Authored Code

When agents write most of the PRs, human review stops being the quality floor. Deterministic gates become the part that scales:

- `crap` catches complex code the agent shipped without matching tests.
- `mutation` catches tests the agent wrote that do not actually test the code.
- `coverage` and complexity trends feed drift telemetry — signal that agent output is regressing before users notice.
- `trust` combines those into one actionable report, so reviewers (human or LLM-based) have a stable ground truth.

interlock is complementary to LLM-based reviewers such as CodeRabbit, Greptile, or Diamond. They catch style, design, and intent. interlock catches what is machine-verifiable: complexity, coverage, mutation survival, dependency hygiene, architectural drift. Runs in seconds, same command locally and in CI.

## Adoption Presets

Presets are optional defaults under `[tool.interlock]` or `~/.config/interlock/config.toml`. Explicit values in the same layer override preset defaults, so you can manually tune thresholds in `pyproject.toml` after choosing a preset.

```toml
[tool.interlock]
preset = "baseline"  # "baseline" | "strict" | "legacy"
```

- `baseline` lowers first-adoption friction: advisory CRAP, relaxed thresholds, mutation off in CI, acceptance off in `check`.
- `strict` is for mature repositories: stronger thresholds, blocking CRAP and mutation, mutation in CI, acceptance in `check`.
- `legacy` is for ratcheting existing repositories: very permissive thresholds, advisory gates, mutation off in CI.

`agent-safe` is intentionally unsupported. If configured, `interlock doctor` reports it as an unsupported preset instead of resolving agent-specific defaults.

## Configuration

Nothing is required. `interlock` walks up from CWD to the nearest `pyproject.toml` and auto-detects:

- project root: first directory with `pyproject.toml`
- test runner: pytest if pytest config/deps/imports are present, otherwise unittest
- test dir: first existing of `tests/`, `test/`, `src/tests/`
- source dir: build-backend declarations, package layouts, `src/<pkg>`, top-level packages, or the project root
- test invoker: `uv run` when `uv.lock` exists, else `python -m`
- features dir: first existing of `tests/features/`, `features/`, `<test_dir>/features/`

Override anything via `[tool.interlock]` in `pyproject.toml`:

```toml
[tool.interlock]
preset = "baseline"

# Paths / runners
src_dir = "mypkg"
test_dir = "tests"
test_runner = "pytest"            # "pytest" | "unittest"
test_invoker = "python"           # "python" | "uv"
pytest_args = ["-q", "-x"]

# Thresholds
coverage_min = 80
crap_max = 30.0
complexity_max_ccn = 15
complexity_max_args = 7
complexity_max_loc = 100
mutation_min_coverage = 70.0
mutation_max_runtime = 600
mutation_min_score = 80.0

# Gate behavior
enforce_crap = true
run_mutation_in_ci = false
enforce_mutation = false
mutation_ci_mode = "off"          # "off" | "incremental" | "full"
mutation_since_ref = "origin/main"

# Acceptance
acceptance_runner = "pytest-bdd"  # "pytest-bdd" | "behave" | "off"
features_dir = "tests/features"
run_acceptance_in_check = false
```

Precedence, lowest to highest:

1. Bundled dataclass defaults.
2. User-global preset defaults from `~/.config/interlock/config.toml`.
3. User-global explicit values.
4. Project preset defaults from `[tool.interlock]`.
5. Project explicit values.
6. CLI flags inside tasks, such as `--min=`, `--max=`, `--max-runtime=`, `--min-score=`, and `--min-coverage=`.

Example user-global config:

```toml
# ~/.config/interlock/config.toml
preset = "baseline"
coverage_min = 85
```

Run `interlock help` to see the active preset and resolved values.
Run `interlock presets` to see preset options, their main thresholds, and copyable config.
Run `interlock presets set baseline` to set a project preset from the CLI.

## Stages

| Stage | When | What runs |
|-------|------|-----------|
| `interlock check` | Local edit loop | fix -> format -> parallel(typecheck, test, acceptance when opted in) -> deps advisory -> cached CRAP advisory or refresh hint -> suppressions |
| `interlock pre-commit` | Git pre-commit hook | fix/format staged Python files, re-stage, typecheck, tests when source changed |
| `interlock ci` | Pull requests and protected branches | format-check, lint, complexity, deps, typecheck, coverage, arch, acceptance -> CRAP -> optional mutation |
| `interlock nightly` | Scheduled jobs | coverage -> mutation, always blocking on `mutation_min_score` |
| `interlock post-edit` | Editor/agent hook interface | advisory ruff fix + format on changed Python files |
| `interlock setup-hooks` | Convenience installer | writes hooks that call `interlock pre-commit` and `interlock post-edit` |
| `interlock clean` | Local cleanup | removes caches, build artifacts, coverage output, mutation state, and `__pycache__/` |

`interlock pre-commit` and `interlock post-edit` are the stable hook interfaces. `interlock setup-hooks` is a convenience command that installs a git pre-commit hook and merges a Claude Code Stop hook; rerunning it is idempotent.

## Tasks Reference

Correctness:

- `fix` / `format`: ruff lint-fix and format, mutating files.
- `lint` / `format-check`: read-only equivalents for CI.
- `typecheck`: basedpyright.
- `test`: pytest or unittest, auto-detected.
- `acceptance`: Gherkin via pytest-bdd or behave.

Hygiene:

- `audit`: pip-audit CVE scan.
- `deps`: deptry unused, missing, and transitive import checks.
- `arch`: import-linter contracts; default contract forbids source importing tests.

Advanced gates:

- `coverage --min=N`: coverage.py with fail-under. `--min=N` overrides `coverage_min`.
- `crap --max=N [--changed-only]`: CRAP complexity x coverage gate. Blocking depends on `enforce_crap`.
- `mutation --max-runtime=N [--min-coverage=N] [--min-score=N] [--changed-only]`: mutmut. Advisory unless `enforce_mutation = true` or `--min-score=` is passed.
- `trust [--refresh] [--no-trend]`: actionable trust report combining coverage, CRAP, mutation, suspicious-test AST inspection, recent git diff, and next actions. `--refresh` runs coverage first with `--min=0`.

Scaffolding:

- `init`: writes a greenfield `pyproject.toml`, `tests/__init__.py`, and `tests/test_smoke.py`; refuses to overwrite.
- `init-acceptance`: writes a working pytest-bdd example under `tests/features/` and `tests/step_defs/`; refuses to overwrite.

Utility:

- `doctor`: adoption diagnostic. Exempt from the `pyproject.toml` preflight gate.
- `help`: command list plus detected paths, active preset, and thresholds.
- `presets`: show preset options, current values, copyable config, and set a project preset with `interlock presets set <preset>`.
- `version`: print the installed interlock version.

## Acceptance Tests

Drop `.feature` files under `tests/features/` and step definitions under `tests/step_defs/`; `interlock acceptance` runs them via pytest-bdd and shares coverage with `test`. Or run `interlock init-acceptance` for a working example.

Runner detection order:

1. `acceptance_runner` in config (`"pytest-bdd"`, `"behave"`, or `"off"`).
2. Behave layout: `features_dir/steps/` plus `features_dir/environment.py`.
3. `behave` declared as a dependency but not `pytest-bdd`.
4. Default to pytest-bdd.

Acceptance always runs in `interlock ci` when a features directory exists. It is opt-in for `interlock check` via `run_acceptance_in_check = true`.

## Bundled Tool Defaults

When the target project has no config for a given tool, interlock injects its bundled default.

| File | Consumed by | Detected via | Injected flag |
|------|-------------|--------------|---------------|
| `ruff.toml` | `fix`, `format`, `lint`, `format-check` | `[tool.ruff]`, `ruff.toml`, `.ruff.toml` | `--config` |
| `pyrightconfig.json` | `typecheck` | `[tool.basedpyright]`, `pyrightconfig.{json,toml}` | `--project` |
| `coveragerc` | `coverage` | `[tool.coverage.*]`, `.coveragerc` | `--rcfile=` |
| `importlinter_template.ini` | `arch` | `[tool.importlinter]`, `.importlinter`, `setup.cfg` | formatted tempfile plus `--config` |
| `bdd_example.feature` | `init-acceptance` | none | direct copy |
| `bdd_test_example.py` | `init-acceptance` | none | direct copy |
| `bdd_conftest.py` | `init-acceptance` | none | direct copy |
| `scaffold_pyproject.toml` | `init` | none | read plus `{project_name}` substitution |
| `scaffold_test_example.py` | `init` | none | direct copy |

`interlock deps` and `interlock mutation` ship no bundled fallback: deptry applies its built-ins, and mutmut reads the project's `pyproject.toml`.

## Hooks

Use the stable hook interfaces directly when integrating with your own hook manager:

```bash
interlock pre-commit
interlock post-edit
```

Use the convenience installer when you want interlock to write the common hooks:

```bash
interlock setup-hooks
```

It installs:

- `.git/hooks/pre-commit`: runs `interlock pre-commit`. Skip with `git commit --no-verify` when necessary.
- `.claude/settings.json` Stop hook: runs `interlock post-edit` after Claude Code sessions and preserves existing Stop hooks.

Both reference the Python that installed interlock, so reinstall hooks after switching install locations or interpreters.

## Maintainer Release Process

Package identity:

- PyPI distribution: `interlock`
- import package: `interlock`
- CLI command: `interlock`

Trusted Publishing setup:

- PyPI: owner `0xjgv`, repo `interlock`, workflow `release.yml`, environment `pypi`
- TestPyPI: owner `0xjgv`, repo `interlock`, workflow `release.yml`, environment `testpypi`
- No PyPI API token required.

Release checklist:

1. Set `pyproject.toml` version to `0.1.0`.
2. Set `interlock/__init__.py` `__version__` to `0.1.0`.
3. Update `CHANGELOG.md` for `0.1.0`.
4. Run `uv run interlock ci`.
5. Run `uv build`.
6. Trigger `release` manually to publish to TestPyPI.
7. Create matching tag `v0.1.0`.
8. Push tag.
9. Confirm PyPI release, GitHub release assets, and attestations.

See [CHANGELOG.md](./CHANGELOG.md) for release history.
