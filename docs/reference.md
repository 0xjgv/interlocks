# interlocks Reference

This is the detailed command, configuration, and behavior reference. Start with
the [README](../README.md) when you want the fast adoption path.

## Before Interlocks

Python quality often accretes as scattered Ruff, pyright, pytest, coverage,
deptry, pip-audit, import-linter, and mutmut config. Local checks drift from
protected-branch checks, and agent-written tests can look green while missing
behavior. interlocks turns that sprawl into one repeatable gate with explicit
thresholds and closure commands.

## Adoption Presets

Presets are optional defaults under `[tool.interlocks]`. Explicit values in the
same layer override preset defaults, so you can tune thresholds manually after
choosing a preset.

```toml
[tool.interlocks]
preset = "baseline"  # "baseline" | "strict" | "legacy"
```

- `baseline` lowers first-adoption friction: advisory CRAP, relaxed thresholds,
  mutation off in CI, acceptance and property tests off in `check`.
- `strict` is for mature repositories: stronger thresholds, blocking CRAP and
  mutation, mutation in CI, acceptance and property tests in `check`, and
  required Gherkin coverage.
- `legacy` is for ratcheting existing repositories: permissive thresholds,
  advisory gates, mutation off in CI.

`agent-safe` is intentionally unsupported. If configured, `interlocks doctor`
reports it as an unsupported preset instead of resolving agent-specific
defaults.

Run `interlocks presets` to see preset options, main thresholds, and copyable
config. Run `interlocks presets set baseline` to set a project preset from the
CLI.

## Configuration

Nothing is required. `interlocks` walks up from CWD to the nearest
`pyproject.toml` and auto-detects:

- project root: first directory with `pyproject.toml`
- test runner: pytest if pytest config or declared deps are present, otherwise
  unittest
- test dir: first existing of `tests/`, `test/`, `src/tests/`
- source dir: build-backend declarations, package layouts, `src/<pkg>`,
  top-level packages, or the project root
- test invoker: `uv run` when `uv.lock` exists, else `python -m`
- features dir: first existing of `tests/features/`, `features/`,
  `<test_dir>/features/`

Override anything via `[tool.interlocks]` in `pyproject.toml`:

```toml
[tool.interlocks]
preset = "baseline"

# Paths / runners
src_dir = "mypkg"
test_dir = "tests"
properties_dir = "properties"
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
run_properties_in_check = false
require_acceptance = false        # true -> fail stages when no Gherkin scenarios are present

# Evaluation policy / cached evidence
evaluate_dependency_freshness = false
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
4. CLI flags inside tasks, such as `--min=`, `--max=`, `--max-runtime=`,
   `--min-score=`, and `--min-coverage=`.

Inspection commands:

```bash
interlocks help
interlocks config
interlocks config show ruff
interlocks config show basedpyright
interlocks config show coverage
interlocks config show import-linter
```

## Stages

| Stage | When | What runs |
|-------|------|-----------|
| `interlocks check` | Local edit loop | fix -> format -> parallel(typecheck, test, acceptance/properties when opted in) -> deps advisory -> cached CRAP advisory or refresh hint -> suppressions |
| `interlocks pre-commit` | Git pre-commit hook | fix/format staged Python files, re-stage, typecheck, tests when source changed |
| `interlocks ci` | Pull requests and protected branches | format-check, lint, complexity, audit, deps, typecheck, coverage including properties, arch, acceptance -> CRAP -> optional mutation per `mutation_ci_mode`; writes `.interlocks/ci.json` timing evidence |
| `interlocks nightly` | Scheduled jobs | coverage including properties -> audit with warn-skips on transient pip-audit failures -> mutation, always blocking on `mutation_min_score` |
| `interlocks post-edit` | Editor/agent hook interface | advisory ruff fix + format on changed Python files |
| `interlocks setup` | Local onboarding | installs/checks hooks, agent docs, and Claude skill; `--ci=github` installs/checks GitHub CI wiring |
| `interlocks clean` | Local cleanup | removes caches, build artifacts, coverage output, mutation state, and `__pycache__/` |

`mutation_ci_mode` controls how `interlocks ci` invokes mutmut:

- `"off"`: skip mutation in CI. The legacy flag `run_mutation_in_ci = true`
  still forces a full run.
- `"incremental"`: mutate only files changed vs `mutation_since_ref`, default
  `origin/main`. Empty diff is a clean skip.
- `"full"`: run the full mutmut suite.

Nightly always runs the full suite plus score gate, so PRs can trade some
mutation signal for speed while scheduled jobs catch anything incremental mode
misses.

## Tasks

Correctness:

- `fix` / `format`: Ruff lint-fix and format, mutating files.
- `fix-optimize` / `unblock [--apply]`: discover fixable Ruff rules on the
  changed file set, pick the highest-value subset under budget, and write
  `.lintfix/plan.json` plus `.lintfix/optimize.json`. `--metrics` writes
  `.lintfix/metrics.json`; `--annotate` emits GitHub Actions annotations.
- `fix-rule --rule=<CODE> [--apply]`: rule-scoped support fix. Auto-mode rules
  can mutate after budget and verifier pass; escrow-mode rules write
  `.lintfix/escrow/<rule>.patch`.
- `lint` / `format-check`: read-only equivalents for CI.
- `typecheck`: basedpyright.
- `test`: pytest or unittest, auto-detected.
- `acceptance`: Gherkin via pytest-bdd or behave. With
  `require_acceptance = true`, registered public behavior IDs must be covered by
  runnable scenarios.
- `properties --profile=check|ci|nightly|default`: pytest + Hypothesis property
  tests under `properties_dir`. The runner-owned `check` profile is intentionally
  small for post-edit feedback; `ci` and `nightly` run deeper generated-input
  sweeps. Root-level `properties/` is the default so normal `pytest tests` runs
  do not accidentally use the wrong Hypothesis profile.
- `property-candidates [--json] [--changed[=REF]] [--uncovered] [--limit=N]`:
  static, read-only ranking of source functions that look suitable for
  property-test hardening. `--uncovered` hides functions already referenced by
  property tests so agents can keep moving through a brownfield sweep. JSON
  output includes filtered, total, referenced, and unreferenced counts plus
  zero-result `next_actions`, so a sweep distinguishes "nothing found" from
  "everything ranked is already referenced."

Hygiene:

- `audit`: pip-audit CVE scan. `audit_severity_threshold` makes high-severity
  policy explicit in `evaluate`.
- `deps`: deptry unused, missing, and transitive import checks.
- `deps-freshness`: explicit package-index check for outdated dependencies; not
  part of default PR CI.
- `arch`: import-linter contracts; default contract forbids source importing
  tests.

Advanced gates:

- `coverage --min=N [--properties[=profile]]`: coverage.py with fail-under.
  `--min=N` overrides `coverage_min`; `--properties` appends property tests
  before reporting, defaulting to the `ci` Hypothesis profile. uv-managed
  projects get Coverage.py injected via `uv run --with`; no project dep
  required.
- `crap --max=N [--changed-only]`: CRAP complexity x coverage gate. Blocking
  depends on `enforce_crap`.
- `mutation --max-runtime=N [--min-coverage=N] [--min-score=N] [--changed-only]`:
  mutmut. Advisory unless `enforce_mutation = true` or `--min-score=` is
  passed.
- `trust [--refresh] [--no-trend]`: actionable trust report combining coverage,
  CRAP, mutation, suspicious-test AST inspection, recent git diff, and next
  actions. `--refresh` runs coverage first with `--min=0 --properties`.
- `evaluate`: read-only 12-check quality scorecard for acceptance, unit tests,
  properties, coverage, mutation, complexity, deps, deps-freshness, security,
  audit-severity, PR speed, and CI. It reports gap-closure command, task/stage
  kind, and rationale without running tests, audits, mutation, or package-index
  lookups.

Scaffolding:

- `init`: writes a greenfield `pyproject.toml`, `tests/__init__.py`, and
  `tests/test_smoke.py`; refuses to overwrite.
- `init-acceptance`: writes a working pytest-bdd example under
  `tests/features/` and `tests/step_defs/`; refuses to overwrite.
- `init-properties`: writes `<properties_dir>/test_example_properties.py`
  (`properties/` by default) when no domain property tests exist; preserves
  existing files and no-ops once domain properties are present.

Utility:

- `config`: list every `[tool.interlocks]` key with type, default, current
  resolved value, source, and description. `--verbose` also prints the compact
  resolved-value block plus precedence, examples, and next steps.
- `doctor`: adoption diagnostic, exempt from the `pyproject.toml` preflight
  gate.
- `setup`: install hooks, agent docs, and Claude skill. `setup --check`
  verifies them read-only.
- `help`: command list plus detected paths, active preset, and thresholds.
- `presets`: show preset options and set a project preset.
- `version`: print the installed interlocks version.

## Acceptance Tests

Drop `.feature` files under `tests/features/` and step definitions under
`tests/step_defs/`; `interlocks acceptance` runs them via pytest-bdd and shares
coverage with `test`. Or run `interlocks init-acceptance` for a working
example.

Behavior coverage uses explicit IDs for observable public behavior. For
interlocks itself, IDs live in `interlocks/behavior_coverage.py` near
public-boundary inventory entries. Downstream projects with no registry keep
zero-config behavior.

Mark scenarios with either syntax immediately above `Scenario` or
`Scenario Outline`:

```gherkin
# req: task-coverage
@req-stage-ci
Scenario: quality gates run
  Given a project
```

Multiple IDs may attach to one scenario. Comments or tags inside scenario steps
do not count. Under `require_acceptance = true`, runnable projects fail when a
live behavior ID is uncovered, a scenario marker is stale, or duplicate live IDs
exist. Remediation names the behavior ID and suggests adding `# req: <id>` or
`@req-<id>`.

Advisory trace evidence is separate from behavior markers. Run
`interlocks acceptance --trace` to request runtime public-symbol evidence; trace
failures, missing evidence, or newly untraced symbols are diagnostic-only in
this release and do not change `acceptance`, `ci`, or `check` exit codes.

Runner detection order:

1. `acceptance_runner` in config: `"pytest-bdd"`, `"behave"`, or `"off"`.
2. Behave layout: `features_dir/steps/` plus `features_dir/environment.py`.
3. `behave` declared as a dependency but not `pytest-bdd`.
4. Default to pytest-bdd.

Acceptance always runs in `interlocks ci` when a features directory exists. It
is opt-in for `interlocks check` via `run_acceptance_in_check = true`. Set
`require_acceptance = true` under `[tool.interlocks]` to make missing Gherkin
scenarios and behavior markers stage failures; the `strict` preset enables this
by default. `check` enforces only when `run_acceptance_in_check = true`.

## Bundled Tool Defaults

When the target project has no config for a given tool, interlocks injects its
bundled default.

| File | Consumed by | Detected via | Injected flag |
|------|-------------|--------------|---------------|
| `ruff.toml` | `fix`, `format`, `lint`, `format-check` | `[tool.ruff]`, `ruff.toml`, `.ruff.toml` | `--config` |
| `pyrightconfig.json` | `typecheck` | `[tool.basedpyright]`, `pyrightconfig.{json,toml}` | `--project` |
| `coveragerc` | `coverage` | `[tool.coverage.*]`, `.coveragerc` | `--rcfile=` |
| `importlinter_template.ini` | `arch` | `[tool.importlinter]`, `.importlinter`, `setup.cfg` | formatted tempfile plus `--config` |
| `bdd_example.feature` | `init-acceptance` | none | direct copy |
| `bdd_test_example.py` | `init-acceptance` | none | direct copy |
| `bdd_conftest.py` | `init-acceptance` | none | direct copy |
| `properties_test_example.py` | `init-properties` | none | direct copy |
| `agents_block.md` | `setup`, `agents` | existing `interlocks` doc reference | appended/created |
| `skill/SKILL.md` | `setup`, `setup-skill` | byte match at `.claude/skills/interlocks/SKILL.md` | direct copy |
| `scaffold_pyproject.toml` | `init` | none | read plus `{project_name}` substitution |
| `scaffold_test_example.py` | `init` | none | direct copy |

The bundled `pyrightconfig.json` uses standard mode, suppresses selected noisy
diagnostics for first adoption, and sets `reportDeprecated = "error"`.

`interlocks deps` and `interlocks mutation` ship no bundled fallback: deptry
applies its built-ins, and mutmut reads the project's `pyproject.toml`.

## FAQ

### What style rules are bundled?

When a project has no native config, interlocks supplies bundled defaults for
Ruff, basedpyright, coverage.py, and import-linter. Those defaults are adoption
defaults, not hidden project policy. Inspect them with
`interlocks config show ruff`, `interlocks config show basedpyright`,
`interlocks config show coverage`, or `interlocks config show import-linter`.

For basedpyright, the bundled config is intentionally an adoption baseline. In
bare projects, `il typecheck` passes `--project <bundled pyrightconfig.json>`,
so it may report fewer diagnostics than raw `basedpyright` with no config. Add
`[tool.basedpyright]`, `pyrightconfig.json`, or `pyrightconfig.toml` when you
want project-owned basedpyright policy. The bundled baseline treats deprecated
API usage as an error.

### Do bundled defaults extend my project config?

No. A project-owned `[tool.ruff]`, `ruff.toml`, `[tool.basedpyright]`,
`pyrightconfig.json`, `[tool.coverage]`, `.coveragerc`, `[tool.importlinter]`,
or `.importlinter` replaces the bundled default for that tool. `config show`
reports the active source.

### How do I ignore or skip checks?

Prefer native tool ignores for narrow code-level exceptions. Use presets and
thresholds for policy. Use `interlocks check --changed[=<ref>]` to scope first
adoption to changed files; it skips graph-wide gates, the test suite, and
property tests because those checks are not file-level. Use global skip only
when you need an explicit gate-level escape hatch: `interlocks check
--skip=typecheck`, `INTERLOCKS_SKIP=typecheck interlocks check`, or
`[tool.interlocks] skip = ["typecheck"]`. Unknown skip labels exit 1, and
skipped gates print warnings. The `fix` and `format` labels are one budgeted
lint/format gate — skipping either disables the whole mutation.

### What did setup install, and what remains manual?

`interlocks setup` installs local hooks, agent docs, and the bundled Claude
skill. It does not silently add CI. For GitHub Actions, run
`interlocks setup --ci=github --check` to detect wiring and
`interlocks setup --ci=github` to create `.github/workflows/interlocks.yml`
only when no existing workflow invokes interlocks.

### Which Python versions are supported?

interlocks installs on Python 3.11, 3.12, and 3.13. Python 3.11 is the floor
because `tomllib` is required and bundled defaults target `py311` syntax.

### Is it production-ready?

Yes for Python repositories that want deterministic local/CI quality gates. The
CLI is self-dogfooded, has a reusable GitHub Action, and keeps hosted state out
of the trust path. It is intentionally narrow: no dashboard, no polyglot
orchestration, and no replacement for project-owned tests.

## Crash Reporting

When interlocks itself crashes, the CLI prints a pre-filled GitHub Issues URL
to stderr alongside the canonical Python traceback. The URL opens in your
default browser if one is available; the URL on stderr is the contract,
browser-open is convenience. interlocks never opens a network connection of its
own; only your browser does, only if you choose to follow the link.

Captured fields:

- interlocks version, Python version, platform (`uname -s` / `uname -m`)
- subcommand that crashed
- exception type name
- traceback frames inside `interlocks/`; third-party frames collapse to
  `<external frames: N>`
- UTC timestamp, CI boolean from `CI`, 16-hex fingerprint

What does not leave the machine by construction:

- source code, file contents, or local variables
- environment variables or `sys.argv` values
- hostnames, usernames, or absolute paths
- automatic issue submission

Interactive terminals ask `Report this crash to the interlocks maintainers?
Y/n`. Press Enter, `y`, or `yes` to open the pre-filled GitHub issue in your
browser. Answer `n` / `no`, use a non-interactive shell, or run in CI to keep
the report local only.

Local files:

- `~/.cache/interlocks/crashes/<fingerprint>.json`
- `~/.cache/interlocks/crashes/dedup.json`

Inspect cache state with `interlocks doctor` or by listing
`~/.cache/interlocks/crashes/`.

## Maintainer Release Process

Maintainer-only release details live in
[`../PYPI_RELEASE_CHECKLIST.md`](../PYPI_RELEASE_CHECKLIST.md).

Package identity:

- PyPI distribution: `interlocks`
- import package: `interlocks`
- CLI command: `interlocks`

Trusted Publishing setup:

- PyPI: owner `0xjgv`, repo `interlocks`, workflow `release.yml`,
  environment `pypi`
- TestPyPI: owner `0xjgv`, repo `interlocks`, workflow `release.yml`,
  environment `testpypi`
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

See [`../CHANGELOG.md`](../CHANGELOG.md) for release history.

## Inspiration

Inspired by [Uncle Bob Martin](https://x.com/unclebobmartin/status/2047661738456121506?s=20).
Since Clean Code, we tend to forget the fundamentals: clean code,
deterministic gates, and fast feedback. These fundamentals matter more as
agents write more of the code.
