# pyharness

Ship one tool company-wide. Shared thresholds (CRAP + mutation gates), staged pipelines (`check` / `pre-commit` / `ci` / `nightly`), pre-wired tool defaults. Stop re-plumbing ruff + basedpyright + pytest + pytest-bdd + coverage + mutmut + deptry + import-linter + pip-audit + lizard in every repo.

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

### Pipeline stages — one tool, four pipelines, no per-repo bash

| Stage | When | What runs |
|-------|------|-----------|
| `harness check` | Dev inner loop | fix → format → parallel(typecheck, test, acceptance¹) → deps (advisory) → suppressions report |
| `harness pre-commit` | Git pre-commit hook | fix + format on staged files, re-stage, typecheck, test (only if `src_dir/` touched) |
| `harness ci` | On every PR | parallel(format-check, lint, complexity, deps, typecheck, coverage, arch², acceptance²) → CRAP (blocking) → mutation (if `run_mutation_in_ci`) |
| `harness nightly` | Cron / scheduled | coverage → mutation (**always blocking**: nightly injects `--min-score=<mutation_min_score>` into argv when absent³) |

¹ opt in with `run_acceptance_in_check = true`. ² skips silently if not configured / no features dir. ³ user-supplied `--min-score=` takes precedence.

**Other stages** (direct-invocation only; not part of the pipeline):

- `harness post-edit` — ruff `--fix` + `ruff format` on `git status`-reported changed Python files, advisory only. Drives the Claude Code Stop hook.
- `harness setup-hooks` — writes `.git/hooks/pre-commit` and merges a Stop hook into `.claude/settings.json`. Idempotent.
- `harness clean` — removes `.ruff_cache`, `build/`, `dist/`, `htmlcov/`, `.coverage`, `mutants/`, `.mutmut-cache`, `mutmut-junit.xml`, and every `__pycache__/`.

Your CI workflow becomes one line: `harness ci`. Your pre-commit hook becomes one line: `harness pre-commit`. Your nightly cron becomes one line: `harness nightly`. The logic lives inside pyharness and upgrades with pyharness — no per-repo bash to maintain.

Direct-invocation stages (`post-edit`, `setup-hooks`, `clean`) are documented in more detail under [Stages](#stages).

### Self-dogfooded public-surface contracts

pyharness's own CLI contract is guarded by its own acceptance suite (`tests/features/harness_cli.feature` + `tests/step_defs/`) running via pytest-bdd. Breaking changes to `harness <task>` behaviour fail `harness ci` on this very repo before they ship — the same mechanism you'd use to guard your platform's CLIs.

### Bundled tool defaults — sensible configs ship in the wheel

When your project has no `[tool.ruff]` / `pyrightconfig.json` / `.coveragerc` / `.importlinter`, harness injects its bundled default so `harness lint`, `harness typecheck`, `harness coverage`, `harness arch` all work in a brand-new repo with zero setup. Projects that need custom rules declare their own config and harness steps aside.

See the full inventory — including `init` / `init-acceptance` scaffold templates — in [Bundled tool defaults](#bundled-tool-defaults) under Reference.

## Install

```
pipx install pyharness       # or: uv tool install pyharness
```

Every underlying tool (ruff, basedpyright, pytest, pytest-bdd, coverage, mutmut, deptry, import-linter, pip-audit, lizard) ships with the CLI. No extra `pip install` dance in your project.

## Quickstart

```
cd your-python-project
harness help                 # see detected paths + resolved thresholds
harness check                # fix + format + typecheck + test
harness setup-hooks          # git pre-commit + Claude Code post-edit hook
```

Nothing to configure. Paths, test runner, and invoker auto-detect from `pyproject.toml`. Override any of them under `[tool.harness]` when you need to.

If you run `harness <task>` in a directory without a `pyproject.toml`, it exits 2 with `harness: no pyproject.toml — run 'harness init' to scaffold`. Only `doctor`, `init`, `version`, and `help` are exempt.

Pass `--verbose` to any command to stream subprocess stdout/stderr tagged with the task name. `harness stats --verbose` additionally prints the full breakdown instead of truncating at 10 rows.

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
- `crap --max=N [--changed-only]` — cyclomatic × coverage gate, blocking by default; `--changed-only` scopes to files in `git diff`
- `mutation --max-runtime=N [--min-coverage=N] [--min-score=N] [--changed-only]` — mutmut; advisory unless `enforce_mutation = true` or `--min-score=` passed (see `nightly`)

**Scaffolding**
- `init-acceptance` — write `tests/features/example.feature`, `tests/step_defs/test_example.py`, `tests/step_defs/conftest.py` (refuses to overwrite)

### Stages

Composed entry points. The four pipeline stages (`check`, `pre-commit`, `ci`, `nightly`) are the ones you wire into your workflow — see the [Pipeline stages](#pipeline-stages--one-tool-four-pipelines-no-per-repo-bash) table. The three utility stages below are direct-invocation only.

- `post-edit` — advisory `ruff --fix` + `ruff format` on `git status`-reported changed Python files. Drives the Claude Code Stop hook.
- `setup-hooks` — install `.git/hooks/pre-commit` + merge a Stop hook into `.claude/settings.json`. Idempotent.
- `clean` — removes `.ruff_cache`, `build/`, `dist/`, `htmlcov/`, `.coverage`, `mutants/`, `.mutmut-cache`, `mutmut-junit.xml`, and every `__pycache__/`.

### Reports

- `stats [--no-trend]` — trust-score report (verdict + suspicious tests + hot files); read-only, never exits non-zero. Combines coverage, CRAP, mutation, suspicious-test AST inspection, and recent git diff. Writes `.harness/trust.json` (max 20 entries) so subsequent runs can show trend arrows; pass `--no-trend` to skip the cache write. `--verbose` prints the full breakdown instead of truncating at 10 rows.

### Utility

These commands are exempt from the preflight `pyproject.toml` gate — they exist to diagnose or bootstrap broken setups.

- `doctor` — diagnostic. Prints detected paths (project root / src / test / features), runner, invoker; reports which of `ruff`, `basedpyright`, `coverage`, `mutmut`, `pytest`, `pip-audit`, `deptry`, `import-linter`, `lizard` are on `PATH`; notes whether `.venv/bin/python` exists. Exits 1 only when config itself fails to load.
- `init` — greenfield scaffold. Writes `pyproject.toml` (from a bundled template with `{project_name}` replaced by the cwd basename), `tests/__init__.py`, and `tests/test_smoke.py`. Refuses to overwrite any existing target.
- `version` — print the installed pyharness version.
- `help` — show detected paths + active thresholds.

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

| File | Consumed by | Detected via | Injected flag |
|------|-------------|--------------|---------------|
| `ruff.toml` | `fix` / `format` / `lint` / `format-check` | `[tool.ruff]` · `ruff.toml` · `.ruff.toml` | `--config` |
| `pyrightconfig.json` | `typecheck` | `[tool.basedpyright]` · `pyrightconfig.{json,toml}` | `--project` |
| `coveragerc` | `coverage` | `[tool.coverage.*]` · `.coveragerc` | `--rcfile=` |
| `importlinter_template.ini` | `arch` | `[tool.importlinter]` · `.importlinter` · `setup.cfg` | formatted → tempfile · `--config` |
| `bdd_example.feature` | `init-acceptance` | — | direct copy |
| `bdd_test_example.py` | `init-acceptance` | — | direct copy |
| `bdd_conftest.py` | `init-acceptance` | — | direct copy |
| `scaffold_pyproject.toml` | `init` | — | read + `{project_name}` substitution |
| `scaffold_test_example.py` | `init` | — | direct copy |

`harness deps` and `harness mutation` ship no bundled fallback — deptry applies its built-ins, and mutmut reads the project's `pyproject.toml` directly.

Run `harness help` to see what was detected and which thresholds are in effect.

### Hooks

```
harness setup-hooks
```

Installs two things:

- **`.git/hooks/pre-commit`** — runs `harness pre-commit` (staged files only). Skip with `git commit --no-verify` if you must.
- **`.claude/settings.json` Stop hook** — runs `harness post-edit` after Claude Code sessions, formatting any files the session touched. Merges into existing hooks; idempotent.

Both reference the Python that installed pyharness, so they survive venv changes.

See [CHANGELOG.md](./CHANGELOG.md) for release history.
