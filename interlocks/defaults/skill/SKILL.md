---
name: interlocks
description: >
  Drive the interlocks Python quality CLI (lint, format, typecheck, test,
  coverage, acceptance, audit, deps, arch, CRAP, mutation). Triggers when the
  repo's pyproject.toml has `[tool.interlocks]`, when `.claude/settings.json`
  calls `interlocks post-edit`, when `AGENTS.md`/`CLAUDE.md` references
  `interlocks check`, or when a git pre-commit hook invokes `interlocks
  pre-commit`. Use when about to edit Python, after finishing a change, when a
  gate failed, or when setting up quality gates in a Python repo.
argument-hint: [check | diagnose | configure | scaffold]
disable-model-invocation: false
---

# interlocks

Quality gates run via `interlocks <subcommand>`. You drive the CLI; this skill says when and how to read output. CLI is source of truth.

## Invocation

Prefer `uvx --from interlocks il <cmd>` over project install. Zero-config, no venv pollution, works in any Python repo:

```sh
uvx --from interlocks il check
uvx --from interlocks il ci
uvx --from interlocks il config
```

`il` is the short alias (`interlocks`/`ilocks`/`ilock`/`ils`/`il` all work). Drop to bare `interlocks <cmd>` only when the project lists `interlocks` as a dev dep.

## Trigger signals

This repo is an interlocks repo when any of these hold:

- `[tool.interlocks]` table in `pyproject.toml`
- `interlocks` listed in deps / dep-groups
- `AGENTS.md` / `CLAUDE.md` references `interlocks`
- `.git/hooks/pre-commit` calls `interlocks pre-commit`
- `.github/workflows/*.yml` invokes the `interlocks` action
- `.claude/settings.json` has a `Stop` hook running `interlocks post-edit`

If none hold, this skill should not have loaded — bail.

## Workflow router

Branch on intent:

- **Authoring code** → `uvx --from interlocks il check` after edits. Fast: fix + format + typecheck + test.
- **Pre-commit** → automated via hook. If missing, run `uvx --from interlocks il pre-commit`.
- **Pre-PR / verifying CI parity** → `uvx --from interlocks il ci`. Adds coverage, CRAP, audit, deps, arch.
- **Investigating one failure** → run the single gate: `il lint`, `il typecheck`, `il coverage`, etc.
- **Setting up a fresh repo** → `il doctor` → `il init` (greenfield only) → `il setup-hooks` → `il agents`.
- **Long-running gates** → `il nightly` (full coverage + mutation).

## Reading the output

- **Symbols**: `✓` ok, `✗` fail, `⚠` skip.
- **Exit codes**: `0` pass, `1` blocking gate failed, `2` preflight (no `pyproject.toml` reachable).
- **Advisory ≠ blocking**: a red `✗` does not always mean exit 1. CRAP and mutation default to advisory. Check exit code, not just symbol.
- **Skips are signals**: `⚠` usually means a tool isn't installed or a config key is unset. Fix env, don't ignore.

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
- Inspect: `uvx --from interlocks il config` (full key list with current values).
- Common knobs: `coverage_min`, `crap_max`, `enforce_crap`, `enforce_mutation`, `mutation_ci_mode`, `preset` (`baseline`|`strict`|`legacy`).
- Switching presets: `il presets set strict`. Don't hand-edit each threshold.

## When NOT to run interlocks

- Doc-only edits (`*.md`, `LICENSE`).
- Inside `vendor/` or generated dirs.
- No trigger signal present (skill shouldn't have loaded — bail).

## Escalation — ask the user first

- Lowering a threshold (`coverage_min`, `crap_max`, `mutation_min_score`).
- Preset downgrade (`strict` → `baseline` → `legacy`).
- Disabling enforcement (`enforce_crap=false`, `enforce_mutation=false`).
- Bypassing a hook (`git commit --no-verify`, force-push).
- Adding a new gate or task — refer to `CLAUDE.md` "adding a new gate" block in the interlocks repo.
