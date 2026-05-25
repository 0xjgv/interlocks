# interlocks

One deterministic Python quality loop for local edits, git hooks, CI, and
agent-authored pull requests.

```bash
uvx --from interlocks il doctor
uvx --from interlocks il check
uvx --from 'interlocks>=0.2,<0.3' il ci
```

No install is required to start. `doctor` explains what interlocks would run,
`check` runs the local edit loop, and `ci` gates a pull request with the same
quality policy.

interlocks wraps Ruff, basedpyright, coverage.py, mutmut, deptry,
import-linter, pip-audit, lizard, pytest/unittest, and pytest-bdd or behave
behind one command surface. New repositories can rely on auto-detected paths
and bundled tool defaults; mature repositories can use presets or explicit
`[tool.interlocks]` thresholds.

## Who It Is For

Use interlocks when local checks, protected-branch checks, and agent-authored
PRs are drifting apart.

interlocks is not a hosted dashboard, a polyglot quality platform, or a
replacement for project-owned tests. It standardizes repeatable Python gates so
humans and agents review against the same deterministic output.

## First Success

Run a static diagnostic first:

```bash
uvx --from interlocks il doctor
```

`doctor` finds the nearest `pyproject.toml`, detected source/test/features
paths, runner, invoker, active preset, resolved gate values, PATH visibility,
blockers, warnings, local integration state, and shortest next steps. It does
not run tests, typecheck, coverage, mutation, dependency audit, or network
checks.

Run the local quality loop:

```bash
uvx --from interlocks il check
```

`check` runs fix, format, typecheck, tests, optional acceptance and property
tests, advisory dependency hygiene, cached CRAP feedback when fresh coverage
exists, and the suppressions report. It is the command to run after edits
before pushing.

For frequent local use:

```bash
uv tool install interlocks
il check
```

`pipx install interlocks` is also supported. From 0.2 onward, interlocks ships
zero runtime dependencies and dispatches every gate through `uvx` or
`uv run --with` at pinned versions baked into the package, so the tool
environment stays isolated from your project resolver.

Populate the cache for offline use:

```bash
interlocks warm
```

## Choose Your Path

```bash
uvx --from interlocks il doctor
uvx --from interlocks il evaluate
```

Adopt locally:

```bash
interlocks setup
interlocks setup --check
interlocks check
```

`setup` idempotently installs the local feedback loops: git pre-commit hook,
Claude Code Stop hook, `AGENTS.md` / `CLAUDE.md` interlocks block, and bundled
Claude skill at `.claude/skills/interlocks/SKILL.md`. `setup --check` is
read-only and exits non-zero when an integration is missing or stale.

Wire CI:

```bash
uvx --from 'interlocks>=0.2,<0.3' il ci
```

Or use the GitHub Action:

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

Operate as an agent:

```bash
interlocks doctor --json
interlocks config --json
interlocks check --json
```

`interlocks {ci,check,evaluate,trust,doctor,config} --json` emits one
machine-readable JSON object on stdout. Exit codes are unchanged, and
`--json` dominates `--verbose`.

## Validation Flow

| Command | When | What It Proves |
|---------|------|----------------|
| `interlocks doctor` | Before adoption or when confused | Static project detection, config, integrations, blockers, next steps |
| `interlocks check` | After local edits | Fix, format, typecheck, tests, optional acceptance/properties, deps advisory, cached CRAP advisory, suppressions |
| `interlocks pre-commit` | Git hook | Staged-file fix/format, re-stage, typecheck, tests when source changed |
| `interlocks ci` | Pull requests and protected branches | Format-check, lint, complexity, audit, deps, typecheck, coverage including properties, arch, acceptance, CRAP, optional mutation |
| `interlocks nightly` | Scheduled jobs | Coverage including properties, audit, full mutation, blocking on `mutation_min_score` |

`interlocks ci` writes `.interlocks/ci.json` timing evidence. `nightly` catches
slower evidence that may be too expensive for every PR.

Agents can use `interlocks property-candidates --json --uncovered` to rank
pure-ish functions that are not already referenced by property tests.

## Agent Contract

Agents should treat interlocks as the repository quality contract:

- Inspect `interlocks doctor --json` and `interlocks config --json` before
  changing policy or routing around a gate.
- Run `interlocks check` after edits; use `--json` when programmatic parsing is
  needed.
- Never bypass installed hooks or remove interlocks config to make a PR green.
- When `check` or `ci` fails, run the failing gate directly instead of masking
  the failure.
- Prefer project-owned tool config for policy changes and narrow native ignores
  for local exceptions.

More agent and CI guidance lives in
[`docs/agent-workflows.md`](docs/agent-workflows.md).

## Common Recipes

Brownfield adoption:

```bash
interlocks check --changed
interlocks check --changed=HEAD~1
```

`--changed` scopes file-level gates such as fix, format, typecheck, and CRAP to
the diff against the configured base ref. Graph-wide gates and the test suite
are skipped with a banner; property tests are skipped too because they are
property-wide rather than file-level. Run `interlocks test` and
`interlocks properties --profile=check` separately when you want the full suite.

Debug a failing gate:

```bash
il lint
il typecheck
il test
il coverage --min=80 --properties
il deps
il audit
il arch
il acceptance
```

Use adoption presets:

```toml
[tool.interlocks]
preset = "baseline"  # "baseline" | "strict" | "legacy"
```

`baseline` lowers first-adoption friction, `strict` strengthens mature
repositories, and `legacy` supports ratcheting existing repositories. The
unsupported `agent-safe` preset is rejected by `doctor` instead of resolving
agent-specific defaults.

Keep CI offline after warmup:

```bash
interlocks warm
UV_OFFLINE=1 interlocks ci
```

Unblock lint or format debt without broad cleanup:

```bash
interlocks unblock
interlocks unblock --apply
interlocks fix-rule --rule=I001 --apply
```

The budgeted lint/format flow is documented in
[`docs/lintfix-mutation-budget-howto.md`](docs/lintfix-mutation-budget-howto.md).

## Command Map

| Need | Command |
|------|---------|
| Adoption diagnostic | `interlocks doctor` |
| Local edit loop | `interlocks check` |
| Git hook command | `interlocks pre-commit` |
| Pull request gate | `interlocks ci` |
| Scheduled deep gate | `interlocks nightly` |
| Tool/config inspection | `interlocks config`, `interlocks config show ruff` |
| Preset inspection | `interlocks presets`, `interlocks presets set baseline` |
| Trust report | `interlocks trust --refresh` |
| Static quality scorecard | `interlocks evaluate` |
| Cleanup | `interlocks clean` |

Full command, config, acceptance, bundled-default, crash-reporting, and release
reference: [`docs/reference.md`](docs/reference.md). Agent and CI workflows:
[`docs/agent-workflows.md`](docs/agent-workflows.md).

## Engineering Principles

interlocks is built around quality through disciplined simplicity: explicit,
readable, flat code beats clever abstraction, and complexity has to earn its
keep.

- Long-term maintainability over short-term convenience.
- Tool-backed confidence through deterministic gates, especially
  `interlocks check`.
- Behavioral correctness first, with focused tests for behavior changes.
- Low entropy: reduce repetition, avoid unnecessary dependencies, keep
  conventions consistent.
- Explicit contracts: typed Python, clear CLI task names, structured config,
  JSON output for agents, predictable workflows.
- Pragmatic rigor: question assumptions, prefer existing architecture, and
  optimize for correctness and clarity without over-engineering.
