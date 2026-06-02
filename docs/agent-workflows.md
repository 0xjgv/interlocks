# Agent And CI Workflows

This guide covers the operating model for humans and AI agents using
interlocks in local loops, pull requests, and CI.

## The Contract

Agents should use the same commands humans use:

```bash
interlocks doctor --json
interlocks config --json
interlocks check --json
```

`interlocks {ci,check,evaluate,trust,doctor,config} --json` emits a single
machine-readable JSON object on stdout. Human chrome is suppressed, exit codes
are unchanged, and `--json` dominates `--verbose`.

Agent rules:

- Inspect `doctor` before assuming paths, runners, presets, or integrations.
- Inspect `config` before changing thresholds or tool policy.
- Run `interlocks check` after code edits before handing work back.
- Use individual gates to debug failures; do not skip or remove failing gates
  without making the policy change explicit.
- Never bypass installed git hooks, Claude Code hooks, or setup-generated agent
  docs to make a pull request green.
- Prefer native tool ignores for narrow code-level exceptions. Use presets and
  thresholds for policy.

## Local Setup

For frequent local use, install once:

```bash
uv tool install interlocks
il check
```

`pipx install interlocks` is also supported when `pipx` is your installed-tool
manager.

From 0.2 onward, interlocks ships zero runtime dependencies and dispatches every
gate (`ruff`, `basedpyright`, `coverage`, `mutmut`, `deptry`, `import-linter`,
`lizard`, `pip-audit`) through `uvx` or `uv run --with` at pinned versions baked
into the package. Installing it as a tool keeps its environment isolated from
the target project. Installing it as a project dependency used to drag a large
transitive graph into project resolvers and could clash with libraries such as
`litellm`.

After installing, populate the cache so subsequent runs can work offline:

```bash
interlocks warm
```

Wire local integrations:

```bash
cd your-python-project
interlocks setup
interlocks setup --check
```

`setup` installs or refreshes the git pre-commit hook, Claude Code Stop hook,
`AGENTS.md` / `CLAUDE.md` interlocks block, and bundled Claude skill at
`.claude/skills/interlocks/SKILL.md`. `setup --check` is read-only and exits
non-zero when local integration state is missing or stale.

For narrow integration troubleshooting:

- `setup --hooks`: writes only the git pre-commit hook and Claude Code Stop hook.
- `setup --agents`: appends or creates the `AGENTS.md` / `CLAUDE.md` interlocks block.
- `setup --skill`: installs or refreshes `.claude/skills/interlocks/SKILL.md`.

Hooks reference the Python that installed interlocks, so rerun
`interlocks setup` after switching install locations or interpreters.
`interlocks hook pre-commit` and `interlocks hook post-edit` are the stable hook
interfaces when integrating with a custom hook manager.

## CI Setup

For repeatable CI, pin or range-pin the package spec:

```bash
uvx --from 'interlocks>=0.2,<0.3' il ci
uvx --from interlocks==0.2.1 il ci
```

If interlocks is already installed in the CI environment, run:

```bash
interlocks ci
```

For GitHub Actions, either run `interlocks setup --ci=github` or copy this
workflow:

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

The reusable action installs interlocks via `uv tool install`, restores the uvx
tool cache from `actions/cache@v4`, runs `interlocks warm`, then runs
`interlocks ci` with `UV_OFFLINE=1`. It writes a concise
`GITHUB_STEP_SUMMARY` when GitHub provides the summary file. The default
installs the latest PyPI release; pin the package through `install-command`
when reproducibility matters:

```yaml
      - uses: 0xjgv/interlocks@v1
        with:
          install-command: uv tool install 'interlocks>=0.2,<0.3'
```

The action does not duplicate lint, typecheck, coverage, CRAP, dependency,
architecture, acceptance, or mutation logic; the CLI remains the source of
truth.

For GitHub CI detection without writing files:

```bash
interlocks setup --ci=github --check
```

To create `.github/workflows/interlocks.yml` only when no existing workflow
invokes interlocks:

```bash
interlocks setup --ci=github
```

## Brownfield Adoption

For onboarding interlocks one pull request at a time on a legacy codebase,
`interlocks check --changed[=<ref>]` scopes file-level gates to the `.py` files
changed against the base ref:

```bash
interlocks check --changed
interlocks check --changed=HEAD~1
```

By default, `--changed` compares against `cfg.changed_ref`, which defaults to
`origin/main`. Override it in config:

```toml
[tool.interlocks]
changed_ref = "main"
```

File-level gates include fix, format, typecheck, and CRAP. Graph-wide gates
such as dependency checks, behavior attribution, and acceptance are skipped
with a banner. Property tests are skipped too because they are property-wide
rather than file-level, and the test suite is skipped because running it would
re-open pre-existing failures the flag is meant to filter out. Run
`interlocks gate test` and `interlocks gate properties --profile=check` separately when
you want the full suite. `pre-commit` and `ci` are unchanged.

## Debugging Failing Gates

When `interlocks check` or `interlocks ci` fails, run the failing gate directly:

```bash
il gate lint
il gate typecheck
il gate test
il gate coverage --min=80 --properties
il gate deps
il gate audit
il gate arch
il gate acceptance
```

Pass `--help` to any gate for available flags. `interlocks help` shows the
common path, and `interlocks help --advanced` lists every subcommand.

Use global skips only as explicit policy:

```bash
interlocks check --skip=typecheck
INTERLOCKS_SKIP=typecheck interlocks check
```

Or in project config:

```toml
[tool.interlocks]
skip = ["typecheck"]
```

Unknown skip labels exit 1, and skipped gates print warnings. `fix` and
`format` are one budgeted lint/format gate — skipping either disables it.

## Advanced Evidence Gates

For mature repositories and AI-authored review, use `gate crap`, `gate mutation`,
`gate properties`, `trust`, and `evaluate` beyond the local edit loop.

- `gate crap` catches complex code without matching tests.
- `gate mutation` catches tests that execute code without checking behavior.
- `gate properties` catches invariant breaks across generated inputs.
- `property-candidates --json --uncovered` ranks source functions for the next
  property-test slice, suppressing functions already referenced by property tests.
- `gate coverage` and complexity trends expose drift before users notice.
- `trust` combines coverage, CRAP, mutation, suspicious-test inspection, recent
  git diff, and next actions into one report.
- `evaluate` gives a read-only 12-check scorecard for policy and evidence gaps.

interlocks complements LLM-based reviewers such as CodeRabbit, Greptile, or
Diamond. They catch style, design, and intent. interlocks catches
machine-verifiable evidence: complexity, coverage, mutation survival,
dependency hygiene, and architectural drift.

## Unblock Flow

When a pull request is blocked by several fixable lint families, use
`fix optimize` or its alias `fix unblock`:

```bash
interlocks fix unblock
interlocks fix unblock --apply
```

It discovers fixable Ruff rules on the changed file set, picks the
highest-value subset under a budget, and writes `.lintfix/plan.json` plus
`.lintfix/optimize.json`. With `--metrics`, it also writes
`.lintfix/metrics.json`. `--apply` applies the selected subset, verifies, and
restores the tree on failure.

When a pull request is blocked by one lint family, use `fix rule`:

```bash
interlocks fix rule --rule=I001
interlocks fix rule --rule=I001 --apply
interlocks fix rule --rule=F401 --apply
```

`fix rule` plans by default. With `--apply`, it mutates only when the rule mode
is `auto`, budgets pass, and the verifier passes. Escrow-mode rules such as
`F401` and `UP*` write `.lintfix/escrow/<rule>.patch` for review instead of
mutating the tree.

Defaults:

- Non-mutating unless `--apply` is passed.
- Base ref `origin/main`, override with `--base=<ref>`.
- Budget profile `unblock`; use `--budget=renovation` for planned cleanup.
- `.lintfix/replay.json` is auto-discovered when present to weight rule values
  from replay history. Use `--no-stats` to ignore it, or `--stats=<path>` to
  point elsewhere.
- Verifier defaults to `interlocks ci`; override with
  `--verify-cmd="<command>"`.
- On verifier failure, the original tree is restored and the patch is preserved
  at `.lintfix/failed.patch`.

Initial rule modes:

| Rule | Mode | Notes |
|------|------|-------|
| `I001` | auto | Import sort; low churn, no semantic change. |
| `W292` | auto | EOF newline. |
| `F401` | escrow | Unused import; may have side effects or re-export intent. |
| `UP*` | escrow | Type-annotation or syntax modernization. |
| `SIM*`, `C4*` | advisory | Control-flow or collection rewrites; review noise. |

In CI, an advisory unblock step can emit annotations and metrics without
changing the exit code:

```yaml
- name: Unblock pass (advisory)
  if: always()
  run: interlocks fix optimize --base=origin/main --annotate --metrics
```

`--annotate` emits `::notice::` and `::warning::` PR annotations, never
`::error::`. The practical lintfix walkthrough is in
[`lintfix-mutation-budget-howto.md`](lintfix-mutation-budget-howto.md).

The phased commands behind `fix optimize` remain available for finer control:
`fix plan`, `fix replay`, `fix annotate`, and `fix metrics`. The full design is
in [`../lint_fix_harness_SPEC.md`](../lint_fix_harness_SPEC.md).
