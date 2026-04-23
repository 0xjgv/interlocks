# pyharness

Ship one tool company-wide. Shared thresholds (CRAP + mutation gates), staged pipelines (`check` / `pre-commit` / `ci` / `nightly`), pre-wired tool defaults. Stop re-plumbing ruff + basedpyright + pytest + coverage + mutmut + deptry + import-linter + pip-audit + lizard in every repo.

Built for platform / devex teams who need every Python service in the org to pass the same gates with the same config surface — without copy-pasting `[tool.ruff]` and pinning six dev-dependencies in each repo.

## Why not just `pip install ruff basedpyright pytest coverage mutmut deptry import-linter lizard pip-audit`?

Because installing the tools is the easy part. The hard parts are what pyharness exists to do:

### Shared thresholds — one `[tool.harness]` table is the source of truth

Every gate (coverage, CRAP, mutation, complexity) reads the same table. Bump `coverage_min` once, every project that upgrades pyharness inherits it. Ship `crap_max` and `mutation_min_score` as org defaults via the bundled wheel or `~/.config/harness/config.toml`; projects override only when they must.

```toml
[tool.harness]
coverage_min = 80
crap_max = 30.0
complexity_max_ccn = 15
mutation_min_score = 80.0
enforce_crap = true
```

No more drift between a team's `.coveragerc`, `pyproject`'s `[tool.coverage.report] fail_under`, and the CI script's `--fail-under=` flag.

### Staged gates — one tool, four pipelines, no per-repo bash

| Stage | When | What runs |
|-------|------|-----------|
| `harness check` | Dev inner loop | fix → format → parallel(typecheck, test, acceptance¹) → deps (advisory) |
| `harness pre-commit` | Git pre-commit hook | fix + format on staged files, re-stage, typecheck, test (only if `src_dir/` touched) |
| `harness ci` | On every PR | parallel(format-check, lint, complexity, deps, typecheck, coverage, arch², acceptance²) → CRAP (blocking) → mutation (if `run_mutation_in_ci`) |
| `harness nightly` | Cron / scheduled | coverage → mutation (**always blocking** on `mutation_min_score`) |

¹ opt in with `run_acceptance_in_check = true`. ² skips silently if not configured / no features dir.

Your CI workflow becomes one line: `uv run harness ci`. Your pre-commit hook becomes one line: `harness pre-commit`. Your nightly cron becomes one line: `harness nightly`. The logic lives inside pyharness, upgrades with pyharness. `harness nightly` overrides `enforce_mutation` — by design it always fails the run when the score drops. That's the point of nightly.

### Self-dogfooded public-surface contracts

pyharness's own CLI contract is guarded by its own acceptance suite (`tests/features/harness_cli.feature` + `tests/step_defs/`) running via pytest-bdd. Breaking changes to `harness <task>` behaviour fail `harness ci` on this very repo before they ship — the same mechanism you'd use to guard your platform's CLIs.

### Bundled tool defaults — sensible configs ship in the wheel

When your project has no `[tool.ruff]` / `pyrightconfig.json` / `.coveragerc` / `.importlinter`, harness injects its bundled default so `harness lint`, `harness typecheck`, `harness coverage`, `harness arch` all work in a brand-new repo with zero setup. Projects that need custom rules declare their own config and harness steps aside.

| Task | Detected via | Bundled fallback |
|------|-------------|------------------|
| `lint` / `fix` / `format` / `format-check` | `[tool.ruff]` or `ruff.toml` / `.ruff.toml` | `harness/defaults/ruff.toml` |
| `typecheck` | `[tool.basedpyright]` or `pyrightconfig.{json,toml}` | `harness/defaults/pyrightconfig.json` |
| `coverage` | `[tool.coverage.*]` or `.coveragerc` | `harness/defaults/coveragerc` |
| `arch` | `[tool.importlinter]` or `.importlinter` / `setup.cfg` | `harness/defaults/importlinter_template.ini` (default: `src ↛ tests`) |

## Install

```
pipx install pyharness       # or: uv tool install pyharness
```

Every underlying tool (ruff, basedpyright, coverage, pytest, pytest-bdd, lizard, mutmut, pip-audit, deptry, import-linter) ships with the CLI. No extra `pip install` dance in your project.

## Quickstart

```
cd your-python-project
harness help                 # see detected paths + resolved thresholds
harness check                # fix + format + typecheck + test
harness setup-hooks          # git pre-commit + Claude Code post-edit hook
```

Nothing to configure. Paths, test runner, and invoker auto-detect from `pyproject.toml`. Override any of them under `[tool.harness]` when you need to.

## Reference

### Tasks

Individual commands. Each reads config + CLI flags. Most call through a shared runner so output is consistent.

**Correctness**
- `fix` / `format` — ruff lint-fix and format (mutates files)
- `lint` / `format-check` — read-only equivalents for CI
- `typecheck` — basedpyright
- `test` — pytest or unittest (auto)
- `acceptance` — Gherkin via pytest-bdd (default) or behave (see below)

**Hygiene**
- `audit` — pip-audit CVE scan
- `deps` — deptry: unused, missing, transitive imports
- `arch` — import-linter contracts (default: `src ↛ tests`)

**Gates**
- `coverage --min=N` — coverage.py with fail-under
- `crap --max=N` — complexity × coverage gate, blocking by default
- `mutation --max-runtime=N` — mutmut; advisory unless `enforce_mutation = true` or `--min-score=` passed (see `nightly`)

**Scaffolding & housekeeping**
- `init-acceptance` — write `tests/features/example.feature`, `tests/step_defs/test_example.py`, `tests/step_defs/conftest.py` (refuses to overwrite)
- `setup-hooks` — install `.git/hooks/pre-commit` + append `post-edit` to `.claude/settings.json` Stop hook
- `clean` — remove caches, build artifacts, mutation state
- `help` — show detected paths + active thresholds

### Acceptance tests (Gherkin)

Drop `.feature` files under `tests/features/` and step definitions under `tests/step_defs/`; `harness acceptance` runs them via pytest-bdd and shares coverage with `test`. Or run `harness init-acceptance` for a working example.

Runner detection order:
1. `acceptance_runner` in config (`"pytest-bdd"` | `"behave"` | `"off"`) — explicit override
2. behave layout (`features_dir/steps/` + `features_dir/environment.py`) → behave
3. `behave` in dependencies but not `pytest-bdd` → behave
4. default → pytest-bdd

Acceptance always runs in `harness ci` when a features dir exists. It's opt-in for `harness check` via `run_acceptance_in_check = true`.

### Configuration

Nothing is required. `harness` walks up from CWD to the nearest `pyproject.toml` (pytest-style rootdir) and auto-detects:

- **project root** — first dir with `pyproject.toml`
- **test runner** — pytest if any of `[tool.pytest.*]`, `pytest.ini`, `<test_dir>/conftest.py`, or pytest is declared/importable; otherwise unittest
- **test dir** — first existing of `tests/`, `test/`, `src/tests/`
- **source dir** — `[tool.uv.build-backend] module-name`, Hatch/Setuptools packages, `src/<pkg>`, or the first top-level `__init__.py`-bearing dir
- **test invoker** — `uv run` when `uv.lock` is present, else `python -m`
- **features dir** — first existing of `tests/features/`, `features/`, `<test_dir>/features/`

Override anything via `[tool.harness]` in `pyproject.toml` — all keys optional:

```toml
[tool.harness]
# Paths / runners
src_dir = "mypkg"
test_dir = "tests"
test_runner = "pytest"            # or "unittest"
test_invoker = "python"           # or "uv"
pytest_args = ["-q", "-x"]

# Thresholds — single source of truth, every gate reads these
coverage_min = 80                 # coverage fail-under
crap_max = 30.0                   # CRAP ceiling
complexity_max_ccn = 15           # lizard cyclomatic complexity cap
complexity_max_args = 7           # lizard argument count cap
complexity_max_loc = 100          # lizard LOC cap
mutation_min_coverage = 70.0      # skip mutation if suite coverage below this
mutation_max_runtime = 600        # mutmut SIGTERM timeout (seconds)
mutation_min_score = 80.0         # kill ratio (%) enforced when blocking

# Gate enforcement
enforce_crap = true               # `crap` exits 1 on offenders (false = advisory)
run_mutation_in_ci = false        # include mutation in `harness ci`
enforce_mutation = false          # `mutation` exits 1 when score < mutation_min_score

# Acceptance
acceptance_runner = "pytest-bdd"  # "pytest-bdd" | "behave" | "off" (auto if unset)
features_dir = "tests/features"   # auto if unset
run_acceptance_in_check = false   # include acceptance in `harness check`
```

### Precedence cascade

Highest wins:

1. **CLI flags** — `--min=`, `--max=`, `--max-runtime=`, `--min-score=`
2. **Project `[tool.harness]`** in the nearest `pyproject.toml`
3. **User-global `~/.config/harness/config.toml`** (respects `$XDG_CONFIG_HOME`) — same keys, no `[tool.harness]` wrapper
4. **Bundled defaults** — values above, plus tool configs under `harness/defaults/` when the project has none

Example `~/.config/harness/config.toml` (org-wide baseline for every dev):

```toml
coverage_min = 85
crap_max = 25.0
```

### Bundled tool defaults

When the target project has no config for a given tool, harness injects its bundled default. This is why `harness lint`, `harness typecheck`, `harness coverage`, and `harness arch` work in a brand-new repo with no setup.

| Task | Detected via | Bundled fallback | Injected flag |
|------|-------------|------------------|---------------|
| `lint` / `fix` / `format` / `format-check` | `[tool.ruff]` or `ruff.toml` / `.ruff.toml` | `harness/defaults/ruff.toml` | `--config` |
| `typecheck` | `[tool.basedpyright]` or `pyrightconfig.{json,toml}` | `harness/defaults/pyrightconfig.json` | `--project` |
| `coverage` | `[tool.coverage.*]` or `.coveragerc` | `harness/defaults/coveragerc` | `--rcfile=` |
| `arch` | `[tool.importlinter]` or `.importlinter` / `setup.cfg` | `harness/defaults/importlinter_template.ini` (default `src ↛ tests`) | `--config` |
| `deps` | `[tool.deptry]` | none — deptry's built-ins apply | — |
| `mutation` | `[tool.mutmut]` | none — mutmut reads the project's `pyproject.toml` | — |

Run `harness help` to see what was detected and which thresholds are in effect.

### Hooks

```
harness setup-hooks
```

Installs two things:

- **`.git/hooks/pre-commit`** — runs `harness pre-commit` (staged files only). Skip with `git commit --no-verify` if you must.
- **`.claude/settings.json` Stop hook** — runs `harness post-edit` after Claude Code sessions, formatting any files the session touched. Merges into existing hooks; idempotent.

Both reference the Python that installed pyharness, so they survive venv changes.

## Changelog

### Blocking CRAP (breaking default)

`harness crap` used to be advisory (printed offenders, exit 0). It now **exits 1 by default** when any function's CRAP score exceeds `crap_max` (30.0). Restore the old behaviour with:

```toml
[tool.harness]
enforce_crap = false
```

Mutation stays advisory by default — runtime is unbounded on real codebases. Gate it per-PR with `run_mutation_in_ci = true` + `enforce_mutation = true`, or schedule `harness nightly` for a bounded, blocking run.

### Acceptance stage

`harness acceptance` (pytest-bdd default, behave auto-detected) and `harness init-acceptance` (scaffold a working example) are new. Acceptance auto-runs in `ci` when a features dir exists; opt into `check` with `run_acceptance_in_check = true`.
