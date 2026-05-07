# interlocks

For DevEx and platform teams standardizing Python quality across repositories:

```bash
uvx --from interlocks il doctor
uvx --from interlocks il check
uvx --from 'interlocks>=0.1,<0.2' il ci
```

These three commands cover the full adoption arc: diagnose a project, run the local quality loop, and gate a pull request with a pinned spec. No install required to start.

interlocks gives one local/hook/CI command surface for ruff, basedpyright, coverage.py, mutmut, deptry, import-linter, pip-audit, and lizard, while driving the project's pytest/unittest tests and pytest-bdd or behave acceptance suite when available. New repositories can start with auto-detected paths and bundled tool defaults; mature repositories can opt into named presets or explicit `[tool.interlocks]` thresholds when they need stronger gates.

## Who This Is For

Use interlocks when you want one deterministic Python quality loop across a repo or an organization, especially when local checks, CI, and agent-authored PRs are drifting apart.

It is not a hosted dashboard, a polyglot quality platform, or a replacement for project-owned tests. It standardizes the repeatable Python gates so humans and agents review against the same evidence.

## Getting Started

### 1. Diagnose and Explore

```bash
uvx --from interlocks il doctor
uvx --from interlocks il check
```

`doctor` performs static local inspection only: nearest `pyproject.toml`, detected source/test/features paths, runner, invoker, active preset, resolved gate values, PATH visibility, blockers, warnings, local integration state, and shortest next steps. It does not run tests, typecheck, coverage, mutation, dependency audit, or network checks.

`check` runs the local edit loop: fix, format, typecheck, tests, optional acceptance tests, advisory dependency hygiene, cached CRAP feedback when fresh coverage exists, and the suppressions report. It is the command to run after edits before pushing.

The core quality tools ship with the CLI. Unpinned `uvx` follows the latest PyPI release, which is right for exploration.

### 2. Install and Wire Local Integrations

For frequent local use, install once:

```bash
uv tool install interlocks
il check
```

`pipx install interlocks` is also supported when `pipx` is your installed-tool manager.

Wire local integrations with a single command:

```bash
cd your-python-project
interlocks setup
interlocks setup --check
```

`setup` idempotently installs local feedback loops: git pre-commit hook, Claude Code Stop hook, `AGENTS.md` / `CLAUDE.md` interlocks block, and bundled Claude skill at `.claude/skills/interlocks/SKILL.md`. `setup --check` is read-only and exits non-zero when any local integration is missing or stale.

For GitHub Actions CI, run `interlocks setup --ci=github --check` to detect existing wiring, or `interlocks setup --ci=github` to create `.github/workflows/interlocks.yml` only when no existing workflow invokes interlocks.

### 3. Wire CI

For repeatable CI, pin or range-pin the package spec:

```bash
uvx --from 'interlocks>=0.1,<0.2' il ci
# or exact-pin:
uvx --from interlocks==0.1.7 il ci
```

If interlocks is installed in the CI environment, the direct command is:

```bash
interlocks ci
```

For GitHub Actions, either run `interlocks setup --ci=github` or copy this workflow:

```yaml
name: interlocks

on:
  pull_request:
  push:
    branches: [main]

jobs:
  interlocks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: 0xjgv/interlocks@v1
```

The reusable action installs interlocks, runs `interlocks ci`, and writes a concise `GITHUB_STEP_SUMMARY` when GitHub provides the summary file. By default, it installs the latest PyPI release; when reproducibility matters, pin the package through the existing `install-command` input:

```yaml
      - uses: 0xjgv/interlocks@v1
        with:
          install-command: python -m pip install 'interlocks>=0.1,<0.2'
```

The action does not duplicate lint, typecheck, coverage, CRAP, dependency, architecture, acceptance, or mutation logic; the CLI remains the source of truth.

## Brownfield Adoption

For onboarding interlocks one PR at a time on a legacy codebase, `interlocks check --changed[=<ref>]` scopes file-level gates (fix, format, typecheck, CRAP) to the `.py` files changed vs the base ref:

```bash
interlocks check --changed             # scope vs cfg.changed_ref (default origin/main)
interlocks check --changed=HEAD~1      # scope vs explicit ref
```

Graph-wide gates (deps, behavior-attribution, acceptance) and the test suite are skipped with a banner — running them under `--changed` would re-introduce the pre-existing failures that the flag is meant to filter out. Run `interlocks test` separately when you want the full suite. Override the default base with `[tool.interlocks] changed_ref = "main"` (or any git ref). `pre-commit` and `ci` are unchanged.

## Debugging with Individual Gates

When `interlocks check` or `interlocks ci` fails, run the failing gate directly to focus the feedback:

```bash
il lint
il typecheck
il test
il coverage --min=80
il deps
il audit
il arch
il acceptance
```

Pass `--help` to any gate for available flags. `interlocks help` shows the common path, and `interlocks help --advanced` lists every subcommand.

## Advanced Evidence Gates

For mature repositories and AI-authored code review, go beyond the local edit loop with `crap`, `mutation`, `trust`, and `evaluate`. Detailed flags are in the Tasks Reference.

When agents write most of the PRs, human review stops being the quality floor. Deterministic gates become the part that scales:

- `crap` catches complex code the agent shipped without matching tests.
- `mutation` catches tests the agent wrote that do not actually test the code.
- `coverage` and complexity trends feed drift telemetry — signal that agent output is regressing before users notice.
- `trust` combines those into one actionable report, so reviewers (human or LLM-based) have a stable ground truth.

interlocks is complementary to LLM-based reviewers such as CodeRabbit, Greptile, or Diamond. They catch style, design, and intent. interlocks catches what is machine-verifiable: complexity, coverage, mutation survival, dependency hygiene, architectural drift. Runs in seconds, same command locally and in CI.

## Before Interlocks

Python quality often accretes as scattered Ruff, pyright, pytest, coverage, deptry, pip-audit, import-linter, and mutmut config. Local checks drift from protected-branch checks, and agent-written tests can look green while missing behavior. interlocks turns that sprawl into one repeatable gate with explicit thresholds and closure commands.

## Adoption Presets

Presets are optional defaults under `[tool.interlocks]`. Explicit values in the same layer override preset defaults, so you can manually tune thresholds in `pyproject.toml` after choosing a preset.

```toml
[tool.interlocks]
preset = "baseline"  # "baseline" | "strict" | "legacy"
```

- `baseline` lowers first-adoption friction: advisory CRAP, relaxed thresholds, mutation off in CI, acceptance off in `check`.
- `strict` is for mature repositories: stronger thresholds, blocking CRAP and mutation, mutation in CI, acceptance in `check`, and required Gherkin coverage.
- `legacy` is for ratcheting existing repositories: very permissive thresholds, advisory gates, mutation off in CI.

`agent-safe` is intentionally unsupported. If configured, `interlocks doctor` reports it as an unsupported preset instead of resolving agent-specific defaults.

## Configuration

Nothing is required. `interlocks` walks up from CWD to the nearest `pyproject.toml` and auto-detects:

- project root: first directory with `pyproject.toml`
- test runner: pytest if pytest config or declared deps are present, otherwise unittest
- test dir: first existing of `tests/`, `test/`, `src/tests/`
- source dir: build-backend declarations, package layouts, `src/<pkg>`, top-level packages, or the project root
- test invoker: `uv run` when `uv.lock` exists, else `python -m`
- features dir: first existing of `tests/features/`, `features/`, `<test_dir>/features/`

Override anything via `[tool.interlocks]` in `pyproject.toml`:

```toml
[tool.interlocks]
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
skip = []                         # e.g. ["typecheck"] for explicit project policy
enforce_crap = true
run_mutation_in_ci = false
enforce_mutation = false
mutation_ci_mode = "off"          # "off" | "incremental" | "full"
mutation_since_ref = "origin/main"

# Acceptance
acceptance_runner = "pytest-bdd"  # "pytest-bdd" | "behave" | "off"
features_dir = "tests/features"
run_acceptance_in_check = false
require_acceptance = false        # true → fail stages when no Gherkin scenarios are present

# Evaluation policy / cached evidence
evaluate_dependency_freshness = false
# Explicit freshness check; not part of default PR CI.
dependency_freshness_command = "interlocks deps-freshness"
dependency_freshness_stage = "interlocks nightly"
audit_severity_threshold = "high"  # "low" | "medium" | "high" | "critical"
pr_ci_runtime_budget_seconds = 0
pr_ci_evidence_max_age_hours = 24
ci_evidence_path = ".interlocks/ci.json"
```

Precedence, lowest to highest:

1. Bundled dataclass defaults.
2. Project preset defaults from `[tool.interlocks]`.
3. Project explicit values.
4. CLI flags inside tasks, such as `--min=`, `--max=`, `--max-runtime=`, `--min-score=`, and `--min-coverage=`.

Run `interlocks help` to see the active preset and resolved values.
Run `interlocks config` to see every `[tool.interlocks]` key and source.
Run `interlocks config show ruff|basedpyright|coverage|import-linter` to see whether a tool is using bundled defaults or project-owned native config.
Run `interlocks presets` to see preset options, their main thresholds, and copyable config.
Run `interlocks presets set baseline` to set a project preset from the CLI.

## FAQ

### What style rules are bundled?

When a project has no native config, interlocks supplies bundled defaults for ruff, basedpyright, coverage.py, and import-linter. Those defaults are adoption defaults, not hidden project policy. Inspect them with `interlocks config show ruff`, `interlocks config show basedpyright`, `interlocks config show coverage`, or `interlocks config show import-linter`.

For basedpyright, the bundled config is intentionally an adoption baseline. In bare projects, `il typecheck` passes `--project <bundled pyrightconfig.json>`, so it may report fewer diagnostics than raw `basedpyright` with no config. Add `[tool.basedpyright]`, `pyrightconfig.json`, or `pyrightconfig.toml` when you want project-owned basedpyright policy. The bundled baseline treats deprecated API usage as an error.

### Do bundled defaults extend my project config?

No. A project-owned `[tool.ruff]`, `ruff.toml`, `[tool.basedpyright]`, `pyrightconfig.json`, `[tool.coverage]`, `.coveragerc`, `[tool.importlinter]`, or `.importlinter` replaces the bundled default for that tool. `config show` reports the active source.

### How do I ignore or skip checks?

Prefer native tool ignores for narrow code-level exceptions. Use presets and thresholds for policy. Use `interlocks check --changed[=<ref>]` to scope first adoption to changed files. Use global skip only when you need an explicit gate-level escape hatch: `interlocks check --skip=typecheck`, `INTERLOCKS_SKIP=typecheck interlocks check`, or `[tool.interlocks] skip = ["typecheck"]`. Unknown skip labels exit 2, and skipped gates print warnings.

### What did setup install, and what remains manual?

`interlocks setup` installs local hooks, agent docs, and the bundled Claude skill. It does not silently add CI. For GitHub Actions, run `interlocks setup --ci=github --check` to detect wiring and `interlocks setup --ci=github` to create `.github/workflows/interlocks.yml` only when no existing workflow invokes interlocks.

### Which Python versions are supported?

interlocks installs on Python 3.11, 3.12, and 3.13. Python 3.11 is the floor because `tomllib` is required and bundled defaults target `py311` syntax.

### Is it production-ready?

Yes for Python repositories that want deterministic local/CI quality gates. The CLI is self-dogfooded, has a reusable GitHub Action, and keeps hosted state out of the trust path. It is still intentionally narrow: no dashboard, no polyglot orchestration, and no replacement for project-owned tests.

## Stages

| Stage | When | What runs |
|-------|------|-----------|
| `interlocks check` | Local edit loop | fix -> format -> parallel(typecheck, test, acceptance when opted in) -> deps advisory -> cached CRAP advisory or refresh hint -> suppressions |
| `interlocks pre-commit` | Git pre-commit hook | fix/format staged Python files, re-stage, typecheck, tests when source changed |
| `interlocks ci` | Pull requests and protected branches | format-check, lint, complexity, audit, deps, typecheck, coverage, arch, acceptance -> CRAP -> optional mutation (per `mutation_ci_mode`); writes `.interlocks/ci.json` timing evidence |
| `interlocks nightly` | Scheduled jobs | coverage -> audit (warn-skips on transient pip-audit failures) -> mutation, always blocking on `mutation_min_score` |
| `interlocks post-edit` | Editor/agent hook interface | advisory ruff fix + format on changed Python files |
| `interlocks setup` | Local onboarding | installs/checks hooks, agent docs, and Claude skill; `--ci=github` installs/checks GitHub CI wiring |
| `interlocks clean` | Local cleanup | removes caches, build artifacts, coverage output, mutation state, and `__pycache__/` |

`mutation_ci_mode` picks how `interlocks ci` invokes mutmut:

- `"off"` — skip mutation in CI (default; `run_mutation_in_ci = true` legacy flag still forces a full run)
- `"incremental"` — mutates only files changed vs `mutation_since_ref` (default `origin/main`); fast PR signal — runtime scales with PR diff. Empty diff is a clean skip.
- `"full"` — full mutmut suite

Nightly always runs the full suite + score gate, so PRs trade some signal for speed; the scheduled job catches anything the incremental pass misses.

## Tasks Reference

Correctness:

- `fix` / `format`: ruff lint-fix and format, mutating files.
- `lint` / `format-check`: read-only equivalents for CI.
- `typecheck`: basedpyright.
- `test`: pytest or unittest, auto-detected.
- `acceptance`: Gherkin via pytest-bdd or behave. When `require_acceptance = true`, registered public behavior IDs must be covered by runnable scenarios.

Hygiene:

- `audit`: pip-audit CVE scan; `audit_severity_threshold` makes high-severity policy explicit in `evaluate`.
- `deps`: deptry unused, missing, and transitive import checks.
- `deps-freshness`: explicit package-index check for outdated dependencies; not part of default PR CI.
- `arch`: import-linter contracts; default contract forbids source importing tests.

Advanced gates:

- `coverage --min=N`: coverage.py with fail-under. `--min=N` overrides `coverage_min`. uv-managed projects get Coverage.py injected via `uv run --with`; no project dep required.
- `crap --max=N [--changed-only]`: CRAP complexity x coverage gate. Blocking depends on `enforce_crap`.
- `mutation --max-runtime=N [--min-coverage=N] [--min-score=N] [--changed-only]`: mutmut. Advisory unless `enforce_mutation = true` or `--min-score=` is passed.
- `trust [--refresh] [--no-trend]`: actionable trust report combining coverage, CRAP, mutation, suspicious-test AST inspection, recent git diff, and next actions. `--refresh` runs coverage first with `--min=0`.
- `evaluate`: static quality checklist scoring 11 automatable checks (acceptance, unit-tests, coverage, mutation, complexity, deps, deps-freshness, security, audit-severity, pr-speed, ci) for a 0-33 verdict. Reports gap-closure command, task/stage kind, and rationale without running tests, audits, mutation, or package-index lookups. Three checks read explicit policy: `evaluate_dependency_freshness` (deps-freshness), `audit_severity_threshold` (audit-severity), `pr_ci_runtime_budget_seconds` + `.interlocks/ci.json` (pr-speed).

Scaffolding:

- `init`: writes a greenfield `pyproject.toml`, `tests/__init__.py`, and `tests/test_smoke.py`; refuses to overwrite.
- `init-acceptance`: writes a working pytest-bdd example under `tests/features/` and `tests/step_defs/`; refuses to overwrite.

Utility:

- `config`: list every `[tool.interlocks]` key with type, default, description, and current resolved value (read-only). Single source of truth for agents driving setup.
- `doctor`: adoption diagnostic. Exempt from the `pyproject.toml` preflight gate.
- `setup`: install hooks, agent docs, and Claude skill. `setup --check` verifies them read-only.
- `help`: command list plus detected paths, active preset, and thresholds.
- `presets`: show preset options, current values, copyable config, and set a project preset with `interlocks presets set <preset>`.
- `version`: print the installed interlocks version.

## Acceptance Tests

Drop `.feature` files under `tests/features/` and step definitions under `tests/step_defs/`; `interlocks acceptance` runs them via pytest-bdd and shares coverage with `test`. Or run `interlocks init-acceptance` for a working example.

Behavior coverage uses explicit IDs for observable public behavior. For interlocks itself, IDs live in `interlocks/behavior_coverage.py` near public-boundary inventory entries. Downstream projects with no registry keep zero-config behavior.

Mark scenarios with either syntax immediately above `Scenario` or `Scenario Outline`:

```gherkin
# req: task-coverage
@req-stage-ci
Scenario: quality gates run
  Given a project
```

Multiple IDs may attach to one scenario. Comments or tags inside scenario steps do not count. Under `require_acceptance = true`, runnable projects fail when a live behavior ID is uncovered, a scenario marker is stale, or duplicate live IDs exist. Remediation names the behavior ID and suggests adding `# req: <id>` or `@req-<id>`.

Advisory trace evidence is separate from behavior markers. Set `INTERLOCKS_ACCEPTANCE_TRACE=1` to request runtime public-symbol evidence; trace failures, missing evidence, or newly untraced symbols are diagnostic-only in this release and do not change `acceptance`, `ci`, or `check` exit codes.

Runner detection order:

1. `acceptance_runner` in config (`"pytest-bdd"`, `"behave"`, or `"off"`).
2. Behave layout: `features_dir/steps/` plus `features_dir/environment.py`.
3. `behave` declared as a dependency but not `pytest-bdd`.
4. Default to pytest-bdd.

Acceptance always runs in `interlocks ci` when a features directory exists. It is opt-in for `interlocks check` via `run_acceptance_in_check = true`. Set `require_acceptance = true` under `[tool.interlocks]` to make missing Gherkin scenarios and missing behavior markers stage failures; the `strict` preset enables this by default. `check` enforces only when `run_acceptance_in_check = true`.

## Bundled Tool Defaults

When the target project has no config for a given tool, interlocks injects its bundled default.

| File | Consumed by | Detected via | Injected flag |
|------|-------------|--------------|---------------|
| `ruff.toml` | `fix`, `format`, `lint`, `format-check` | `[tool.ruff]`, `ruff.toml`, `.ruff.toml` | `--config` |
| `pyrightconfig.json` | `typecheck` | `[tool.basedpyright]`, `pyrightconfig.{json,toml}` | `--project` |
| `coveragerc` | `coverage` | `[tool.coverage.*]`, `.coveragerc` | `--rcfile=` |
| `importlinter_template.ini` | `arch` | `[tool.importlinter]`, `.importlinter`, `setup.cfg` | formatted tempfile plus `--config` |
| `bdd_example.feature` | `init-acceptance` | none | direct copy |
| `bdd_test_example.py` | `init-acceptance` | none | direct copy |
| `bdd_conftest.py` | `init-acceptance` | none | direct copy |
| `agents_block.md` | `setup`, `agents` | existing `interlocks` doc reference | appended/created |
| `skill/SKILL.md` | `setup`, `setup-skill` | byte match at `.claude/skills/interlocks/SKILL.md` | direct copy |
| `scaffold_pyproject.toml` | `init` | none | read plus `{project_name}` substitution |
| `scaffold_test_example.py` | `init` | none | direct copy |

The bundled `pyrightconfig.json` uses standard mode, suppresses selected noisy diagnostics for first adoption, and sets `reportDeprecated = "error"`.

`interlocks deps` and `interlocks mutation` ship no bundled fallback: deptry applies its built-ins, and mutmut reads the project's `pyproject.toml`.

## Crash Reporting

When interlocks itself crashes, the CLI prints a pre-filled GitHub Issues URL to stderr alongside the canonical Python traceback. The URL opens in your default browser if one is available; the URL on stderr is the contract, browser-open is convenience. **interlocks never opens a network connection of its own** — only your browser does, only if you choose to follow the link.

What gets captured:

- interlocks version, Python version, platform (`uname -s`/`uname -m`)
- subcommand that crashed (e.g. `check`, `lint`)
- exception type name
- traceback frames inside `interlocks/` (third-party frames collapse to `<external frames: N>`)
- UTC timestamp, CI boolean (from `CI` env), 16-hex fingerprint

What does **NOT** leave the machine — by construction:

- No source code, file contents, or local variables
- No environment variables or `sys.argv` values
- No hostnames, usernames, or absolute paths (paths are scrubbed to `~/...` or project-relative)
- No automatic issue submission — interlocks opens a pre-filled GitHub issue in your browser only after you confirm

How reporting works:

- Interactive terminals ask `Report this crash to the interlocks maintainers? Y/n`.
- Press Enter, `y`, or `yes` to open the pre-filled GitHub issue in your browser.
- Answer `n`/`no`, use a non-interactive shell, or run in CI to keep the report local only.

Where local files live:

- `~/.cache/interlocks/crashes/<fingerprint>.json` — full payload, mode 0600 in mode 0700 dir
- `~/.cache/interlocks/crashes/dedup.json` — 30-day fingerprint window so repeat crashes do not re-prompt

Inspect cache state any time with `interlocks doctor` (look for the `[crash reports]` row) or directly with `ls ~/.cache/interlocks/crashes/`.

To share a crash manually, attach the payload JSON to your issue or paste relevant fields. The same fields are pre-filled in the URL body the browser opens.

## Inspiration

Inspired by [Uncle Bob Martin](https://x.com/unclebobmartin/status/2047661738456121506?s=20). Since *Clean Code*, we tend to forget the fundamentals — clean code, deterministic gates, fast feedback. These fundamentals are back stronger than ever, especially as agents write more of the code.

## Troubleshooting: Integration Escape Hatches

`interlocks setup` is the recommended integration entrypoint and handles hooks, agent docs, and the Claude skill in one command. For cases where you need to install or verify a single integration independently, narrow commands are available:

- `setup-hooks`: writes only the git pre-commit hook (`interlocks pre-commit`) and Claude Code Stop hook (`interlocks post-edit`). Use when you want to manage agent docs and the skill separately.
- `agents`: appends or creates the `AGENTS.md` / `CLAUDE.md` interlocks guidance block only.
- `setup-skill`: installs or refreshes `.claude/skills/interlocks/SKILL.md` only.

Hooks reference the Python that installed interlocks, so rerun `interlocks setup` after switching install locations or interpreters.

`interlocks pre-commit` and `interlocks post-edit` are the stable hook interfaces when integrating with a custom hook manager.

## Maintainer Release Process

Maintainer-only release details live in [PYPI_RELEASE_CHECKLIST.md](./PYPI_RELEASE_CHECKLIST.md).

Package identity:

- PyPI distribution: `interlocks`
- import package: `interlocks`
- CLI command: `interlocks`

Trusted Publishing setup:

- PyPI: owner `0xjgv`, repo `interlocks`, workflow `release.yml`, environment `pypi`
- TestPyPI: owner `0xjgv`, repo `interlocks`, workflow `release.yml`, environment `testpypi`
- No PyPI API token required.

Release checklist:

1. Set `pyproject.toml` version to the next release.
2. Set `interlocks/__init__.py` `__version__` to the same release.
3. Update `CHANGELOG.md` for the release.
4. Run `uv run interlocks ci`.
5. Run `uv build`.
6. Trigger `release` manually to publish to TestPyPI.
7. Create matching `vX.Y.Z` tag.
8. Push tag.
9. Confirm PyPI release, GitHub release assets, and attestations.

See [CHANGELOG.md](./CHANGELOG.md) for release history.
