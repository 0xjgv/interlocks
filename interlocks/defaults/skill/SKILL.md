---
name: interlocks
description: >
  Run interlocks quality gates on a Python project — lint, format, typecheck,
  test, coverage, acceptance, audit, deps, arch, CRAP, mutation — via the
  `interlocks` CLI (alias `il`).
when_to_use: >
  Use after editing Python, before opening a PR, when a quality gate fails,
  or when bootstrapping quality gates in a new Python repo. Trigger signals:
  `[tool.interlocks]` in pyproject.toml; a `Stop` hook running
  `interlocks post-edit` in `.claude/settings.json`; a git pre-commit hook
  invoking `interlocks pre-commit`; `interlocks check` referenced in
  AGENTS.md / CLAUDE.md; or a workflow invoking the `interlocks` action.
paths:
  - "**/*.py"
  - "pyproject.toml"
  - "tests/**"
  - ".github/workflows/*.yml"
---

# interlocks

Quality gates run via `interlocks <subcommand>`. You drive the CLI; this skill says when and how to read output. CLI is source of truth.

## Invocation

Prefer `uvx --from interlocks il <cmd>` over project install for agent runs. Zero-config, no venv pollution, works in any Python repo:

```sh
uvx --from interlocks il check
uvx --from interlocks il ci
uvx --from interlocks il config
uvx --from interlocks il setup --check
```

Unpinned `uvx` is acceptable for ad hoc or exploratory runs because it follows the latest PyPI release. Use pinned or range-pinned specs for repeatable prompts, CI snippets, and shared docs:

```sh
uvx --from 'interlocks>=0.2,<0.3' il ci
uvx --from interlocks==0.2.0 il ci
```

For frequent local human use, `uv tool install interlocks` is appropriate; `pipx install interlocks` is the alternative installed path.

Use `il setup` for local onboarding: hooks, agent docs, bundled Claude skill. Use `il setup --check` for read-only verification. Use `il setup --ci=github` when GitHub Actions should be installed and no existing workflow invokes interlocks. First useful check after setup is `il check`; use `il doctor` when readiness or failures need diagnosis. Use `il version` to print the installed version.

`il` is the short alias (`interlocks`/`ilocks`/`ilock`/`ils`/`il` all work). Drop to bare `interlocks <cmd>` only when the project lists `interlocks` as a dev dep.

## Workflow router

Branch on intent:

- **Authoring code** → `uvx --from interlocks il check` after edits. Fast: fix + format + typecheck + test.
- **Pre-commit** → automated via hook. If missing, run `uvx --from interlocks il pre-commit`.
- **Pre-PR / verifying CI parity** → `uvx --from interlocks il ci`. Adds coverage, CRAP, audit, deps, arch.
- **PR blocked by many lint rules** → `il unblock` (preview, writes `.lintfix/`) then `il unblock --apply`. Discovers + budget-optimizes the full fixable set in one run; `il fix` remains the single-pass safe-fix shortcut.
- **Investigating one failure** → run the single gate: `il lint`, `il typecheck`, `il coverage`, etc.
- **Setting up a fresh repo** → `il init` (greenfield only) → `il setup` → `il check` → `il doctor` if blocked → optional `il setup --ci=github`.
- **Long-running gates** → `il nightly` (full coverage + mutation).
- **Hermetic / offline CI** → `il warm` once to pre-fetch bundled tool wheels into `~/.cache/uv`, then run gates with `UV_OFFLINE=1`. Cached by `interlocks/defaults/tools.py` pins.

## Authoring loop (Gherkin-first)

Before changing public behavior, write the spec, then the test, then the code. Never the other way around.

1. **Acceptance first.** Add or extend a Gherkin scenario under `tests/features/` that names the behavior in user terms. If `features/` is missing, run `il init-acceptance` once, then add the scenario.
2. **Unit test next.** Drop down to `tests/` and write the failing unit assertion that pins the smallest piece of the behavior.
3. **Implement.** Edit `src` until the unit test goes green.
4. **Tighten loop.** `il check` after each edit (lint + format + typecheck + test). Fix red before moving on.
5. **Parity sweep.** `il ci` before opening the PR. Read CRAP offenders, then look at mutmut survivors — improve assertions where mutations slipped through; do not lower thresholds.

`preset = "strict"` wires this loop as enforcement: acceptance becomes required, behavior-attribution blocks, mutation runs incrementally on PRs and full nightly. `baseline` keeps the same loop advisory — the order still matters; the gates simply warn instead of fail.

## Baseline ratchet (autopilot)

If `[tool.interlocks] preset = "progressive"`, the project's quality floor lives in `.interlocks/baseline.json`. Treat it as a hard constraint, not a guideline.

- **Never edit `.interlocks/baseline.json` by hand.** It is bot-managed; the post-merge workflow opens advance PRs as `chore(baseline): advance floor`.
- **When a gate fails citing a floor**, the failure tells you the SHA the floor was set at. Improve assertions / coverage / complexity to clear it; do not lower the floor.
- **Read the floor at any time**: `il baseline show` (human) or `il baseline show --json` (machine).
- **Verify your work moved the curve**: after `il check`, read `.interlocks/run-summary.json` to see the measured numbers and how they compare to the floor.

## Reading the output

- **Symbols**: `✓` ok, `✗` fail, `⚠` skip.
- **Exit codes**: `0` pass, `1` blocking gate failed, `2` preflight (no `pyproject.toml` reachable).
- **Advisory ≠ blocking**: a red `✗` does not always mean exit 1. CRAP and mutation default to advisory. Check exit code, not just symbol.
- **Skips are signals**: `⚠` can mean optional scope, missing evidence, or an explicit global skip. Fix env or config; don't ignore silent gaps.

## Recovery patterns

Per failing gate:

- `lint` → `il fix` (auto-applies safe fixes), re-run `il lint`.
- `format` → `il format` (writes), re-run `il format-check` for CI parity.
- `typecheck` → read basedpyright output, edit, re-run `il typecheck`. Don't widen types blindly.
- `test` → fix the failing assertion. Don't `pytest.skip` to make it pass.
- `coverage` → `il coverage` lists uncovered lines. Add tests. Don't lower the threshold without owner approval.
- `crap` → reduce complexity or raise coverage on the listed function. Threshold lives in `[tool.interlocks] crap_max`.
- `audit` → upgrade the flagged dep. If no fix available, document in `pyproject.toml` and re-run.
- `deps` → remove unused or add missing entries to `pyproject.toml`.
- `arch` → fix the import that violates the contract. Do not weaken `.importlinter`.
- `mutation` → improve assertions in surviving-mutant test files (mutmut output names them). Use `--changed-only` while iterating.

## Config + thresholds

Don't read defaults inline.

- All overrides: `[tool.interlocks]` in `pyproject.toml`.
- Precedence: CLI flag > `[tool.interlocks]` > preset > bundled default.
- Inspect: `uvx --from interlocks il config` (full key list with current values); `il config show ruff|basedpyright|coverage|import-linter` for bundled/project tool config provenance.
- Common knobs: `coverage_min`, `crap_max`, `enforce_crap`, `enforce_mutation`, `mutation_ci_mode`, `preset` (`baseline`|`strict`|`legacy`|`progressive`).
- Switching presets: `il presets set strict`. Don't hand-edit each threshold.

## When NOT to run interlocks

- Doc-only edits (`*.md`, `LICENSE`).
- Inside `vendor/` or generated dirs.
- No trigger signal present (skill shouldn't have loaded — bail).

## Escalation — ask the user first

- Lowering a threshold (`coverage_min`, `crap_max`, `mutation_min_score`).
- Preset downgrade (`strict` → `baseline` → `legacy`).
- Disabling enforcement (`enforce_crap=false`, `enforce_mutation=false`) or adding global `skip` labels.
- Bypassing a hook (`git commit --no-verify`, force-push).
- Adding a new gate or task — refer to `CLAUDE.md` "adding a new gate" block in the interlocks repo.
