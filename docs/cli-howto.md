# How To Use The Interlocks CLI

This guide explains the command surface by job. Use it when you know what you
want to do and need the right command fast.

For the full command contract, flags, exit codes, bundled tool defaults, and
configuration keys, use the [reference](reference.md). For agent and CI
operating rules, use [agent workflows](agent-workflows.md).

## The Shape Of The CLI

The CLI has one top-level form and three nested forms:

```bash
interlocks <command>
interlocks gate <gate>
interlocks fix <mode>
interlocks hook <entrypoint>
```

Top-level commands cover workflows, reports, and project utilities. Gates run
one quality check. Fix commands plan or apply lint and format repairs. Hook
commands are stable entrypoints for installed git or editor hooks.

Use these commands to discover the surface:

```bash
interlocks help
interlocks help --advanced
interlocks help gate coverage
interlocks explain
interlocks explain gate coverage
```

`help` is short by default. `help --advanced` lists every command. `explain`
prints the same catalog as prose, and `explain <command>` prints one command's
usage, mutation behavior, outputs, and exit codes.

## First Run

Start with a read-only diagnostic:

```bash
interlocks doctor
```

`doctor` reports detected project paths, test runner, invoker, preset, gate
values, tool visibility, integration state, blockers, warnings, and next
steps. It runs no tests, typecheck, coverage, mutation, audit, or network
checks.

For a new project, scaffold the minimum structure:

```bash
interlocks init
```

`init` writes `pyproject.toml`, `tests/__init__.py`, and `tests/test_smoke.py`.
It refuses to overwrite an existing `pyproject.toml`.

Add optional test scaffolds when you need them:

```bash
interlocks init --acceptance
interlocks init --properties
```

For an existing project, install local integrations:

```bash
interlocks setup
interlocks setup --check
```

`setup` installs or refreshes the git pre-commit hook, Claude Code Stop hook,
agent docs, and the bundled Claude skill. `setup --check` verifies those files
without writing.

Focused setup modes are available:

```bash
interlocks setup --hooks
interlocks setup --agents
interlocks setup --skill
interlocks setup --ci=github
interlocks setup --ci=github --check
```

## Daily Local Loop

After editing code, run:

```bash
interlocks check
```

`check` is the local edit loop. It runs budgeted lint and format mutation, then
typecheck, tests, optional acceptance tests, optional property tests,
dependency hygiene advisory, cached CRAP advisory, behavior-attribution
advisory, and the suppressions report.

`check` may mutate Python files through the budgeted lint/format step. The
budget comes from your author diff so a small product change does not turn into
a broad cleanup PR.

For brownfield adoption, scope file-level gates to changed Python files:

```bash
interlocks check --changed
interlocks check --changed=HEAD~1
```

`--changed` scopes fix, format, typecheck, and CRAP. It skips graph-wide gates,
the full test suite, acceptance, and properties because those checks cannot be
meaningfully limited to one file list. Run the full gates separately when you
need that evidence:

```bash
interlocks gate test
interlocks gate properties --profile=check
```

Use renovation mode only when the PR is meant to clean up broader lint or
format debt:

```bash
interlocks check --renovate
```

## Debug One Failure

When `check` or `ci` fails, run the failing gate directly:

```bash
interlocks gate format-check
interlocks gate lint
interlocks gate typecheck
interlocks gate test
interlocks gate coverage --min=80 --properties
interlocks gate properties --profile=check
interlocks gate deps
interlocks gate audit
interlocks gate arch
interlocks gate acceptance
interlocks gate behavior-attribution
interlocks gate complexity
interlocks gate crap
interlocks gate mutation --changed-only --since=HEAD
```

Most direct gates are read-only. `interlocks gate format` is the exception: it
formats code with Ruff. Use `interlocks gate format-check` when you want the
read-only equivalent.

Use command help for gate-specific flags:

```bash
interlocks help gate mutation
interlocks help gate coverage
```

## Fix Lint And Format Debt

Use bare `fix` for a direct Ruff lint-fix pass:

```bash
interlocks fix
```

Use the budgeted planner when a PR is blocked by fixable lint or format debt:

```bash
interlocks fix optimize
interlocks fix unblock
interlocks fix unblock --apply
```

`fix unblock` is an alias for `fix optimize`. The command discovers fixable
Ruff rules and format candidates on the changed file set, selects the
highest-value subset under budget, and writes `.lintfix/plan.json` plus
`.lintfix/optimize.json`. With `--apply`, it mutates the selected subset and
verifies the result.

Use `fix rule` when one Ruff rule is blocking the work:

```bash
interlocks fix rule --rule=I001
interlocks fix rule --rule=I001 --apply
```

The phased commands remain available for CI annotations and deeper analysis:

```bash
interlocks fix plan
interlocks fix replay --n=25
interlocks fix annotate
interlocks fix metrics
```

See [budgeted lint and format fixes](lintfix-mutation-budget-howto.md) for the
artifact fields and review-budget model.

## CI And Scheduled Gates

Run CI parity before a pull request or in protected-branch CI:

```bash
interlocks ci
```

`ci` is read-only. It runs format-check, lint, complexity, audit, deps,
typecheck, coverage with properties, architecture checks, acceptance, CRAP, and
optional mutation according to `mutation_ci_mode`. It writes timing evidence to
`.interlocks/ci.json`.

For hosted CI, prefer a pinned `uvx` invocation or the GitHub Action:

```bash
uvx --from 'interlocks>=0.2,<0.3' il ci
```

Run slow evidence on a schedule:

```bash
interlocks nightly
```

`nightly` runs coverage with properties, audit, and full mutation. Mutation is
blocking on `mutation_min_score` in this stage.

## Reports And Planning

Use reports when you need evidence, not mutation:

```bash
interlocks trust --refresh
interlocks evaluate
interlocks property-candidates --json --uncovered
interlocks baseline show
interlocks baseline check
```

`trust` combines coverage, CRAP, mutation, suspicious-test inspection, recent
diff, and next actions. `evaluate` scores the automatable quality checklist
without running tests, audits, mutation, or package-index lookups.
`property-candidates` ranks source functions worth hardening with generated
inputs. `baseline` manages the progressive-preset quality floor in
`.interlocks/baseline.json`.

## Project Utilities

Inspect resolved project policy:

```bash
interlocks config
interlocks config show ruff
interlocks config show basedpyright
interlocks config show coverage
interlocks config show import-linter
```

Work with presets:

```bash
interlocks presets
interlocks presets set baseline
interlocks presets set strict
interlocks presets set legacy
interlocks presets set progressive
```

Prepare offline tool runs:

```bash
interlocks warm
UV_OFFLINE=1 interlocks ci
```

Remove generated local artifacts:

```bash
interlocks clean
```

Print the installed version:

```bash
interlocks version
```

## Output Modes And Policy Flags

Use JSON when automation needs structured output:

```bash
interlocks doctor --json
interlocks config --json
interlocks check --json
interlocks ci --json
interlocks trust --json
interlocks evaluate --json
```

`--json` suppresses human chrome and dominates `--verbose`. Stage-like JSON
payloads include `schema_version`, `gates`, `skipped`, `artifacts`, and an
`agent` block. Agents should run commands from `agent.required_actions` before
handing work back, treat `agent.recommended_actions` as follow-up evidence, and
ask the owner before crossing any listed policy boundary. Use `--verbose` for
more human output. `--quiet` has been removed because minimal output is the
default.

Use skips only as explicit policy:

```bash
interlocks check --skip=typecheck
INTERLOCKS_SKIP=typecheck interlocks check
```

Project-level skips live in `[tool.interlocks]`:

```toml
[tool.interlocks]
skip = ["typecheck"]
```

Unknown skip labels fail. Skipped gates print warnings. The `fix` and `format`
labels are one budgeted lint/format gate, so skipping either disables that
whole mutation step.

## Which Command Should I Run?

| Situation | Command |
|-----------|---------|
| Learn what interlocks sees | `interlocks doctor` |
| Bootstrap a new project | `interlocks init` |
| Install local hooks and agent docs | `interlocks setup` |
| Verify local integrations | `interlocks setup --check` |
| Run after edits | `interlocks check` |
| Scope brownfield feedback to changed Python files | `interlocks check --changed` |
| Debug one failed check | `interlocks gate <gate>` |
| Run pull request parity | `interlocks ci` |
| Run slow scheduled evidence | `interlocks nightly` |
| Inspect resolved policy | `interlocks config` |
| Choose adoption strictness | `interlocks presets set <preset>` |
| Unblock lint or format debt | `interlocks fix unblock` |
| Apply one Ruff rule | `interlocks fix rule --rule=<CODE> --apply` |
| Get a trust report | `interlocks trust --refresh` |
| Score quality gaps without running gates | `interlocks evaluate` |
| Rank property-test targets | `interlocks property-candidates --json --uncovered` |
| Read one command contract | `interlocks explain <command>` |
