# interlocks (npm) — Design Spec

Status: **draft** — not yet committed for build. See "Build Gate" at the bottom.

Sibling to the Python `interlocks` CLI. Same product idea — one enforceable quality workflow with bundled defaults, preset taxonomy, progressive-adoption ratchet — applied to the JS/TS ecosystem and shipped via npm.

This document is the contract for **what** to build, **why**, and **what is explicitly out of scope**. It is not an implementation plan.

---

## Thesis

JS/TS teams already have best-in-class point tools (biome, stryker, vitest, cucumber-js, knip, dependency-cruiser, npm-audit, tsc). What they don't have is **one CLI that composes those tools into a single preset+ratchet+report quality gate**. interlocks (npm) is that composer.

It is a wrapper, not a replacer. Biome owns lint+format. Stryker owns mutation. tsc owns types. interlocks owns *the gate*: presets, thresholds, change-scoping, evidence aggregation, and CI integration.

## Audience

Primary: a platform or DevEx owner of a JS/TS or polyglot Python+TS codebase who already runs ≥2 of {biome, stryker, vitest, cucumber-js, knip, tsc-noEmit} and wants one merge gate with stable thresholds.

Not the audience: TS-only teams content with biome alone; teams without an existing testing or coverage culture (interlocks does not invent quality, it enforces it).

## Wedge

Four slots biome explicitly disowns and stryker/cucumber-js do not stitch together:

1. **Preset taxonomy** — `baseline` / `strict` / `legacy` thresholds bundled, not hand-rolled per repo.
2. **Progressive-adoption ratchet** — `il check --changed[=<ref>]` scopes file-level gates to changed files vs a base ref.
3. **CRAP-as-CI-gate** — composed from cyclomatic complexity + lcov coverage; underserved in JS today (two niche GitHub projects, no widely-adopted tool).
4. **Single evidence report** — a single artifact joining lint+typecheck+test+coverage+mutation+arch+deps+audit results, with consistent severity and threshold semantics.

Not part of the wedge (biome already wins these): linting, formatting, JSON/CSS support.

## Non-goals (v0)

- Replacing biome, stryker, vitest, cucumber-js, knip, dependency-cruiser, tsc.
- A second test runner or formatter.
- Hosted dashboard, PR annotations, GitHub App. Same deferral as the Python product.
- Cross-language threshold comparison with the Python interlocks. Same numbers (e.g., `crap_max=30`) mean different things across languages; do not pretend otherwise.
- Bun-specific framing. Runtime-agnostic.
- Migration tooling from eslint/prettier/jest. Out of scope; users come with a working stack.

## Distribution

- Published to npm as `@interlocks/cli` (or final name TBD; see Open Questions).
- Runtime: Node 20+ LTS. Works under npm, pnpm, yarn, bun. Does **not** require bun.
- Invocation parallel to the Python product:
  - One-shot: `npx @interlocks/cli check`
  - Pinned CI: `npx @interlocks/cli@0.1 ci`
  - Permanent: `npm i -D @interlocks/cli` then `interlocks check`
- A separate GitHub Action mirrors `juangaitan/interlocks-action` semantics.

## Commands (v0)

Mirror the Python surface where the verb makes sense:

| Command | Purpose |
|---|---|
| `interlocks doctor` | Adoption diagnostics: detected tools, package manager, runtime, missing configs. |
| `interlocks check` | Local fast gate. Runs lint + typecheck + tests + coverage at preset thresholds. |
| `interlocks ci` | Full gate. Adds mutation, deps, arch, audit. Single-shot for CI. |
| `interlocks pre-commit` | Hook-manager-agnostic pre-commit subset. |
| `interlocks init` | Greenfield scaffold: `package.json` interlocks key + biome.json + tsconfig + vitest config. |
| `interlocks config` | List config keys + resolved values. |
| `interlocks help` | Subcommands + active thresholds. |

`nightly` deferred until v0.2; mutation in CI is enough at v0.

## Tool mapping

Each gate delegates to a third-party tool via subprocess. interlocks owns thresholds, exit codes, and the report.

| Gate | Tool (default) | Override config |
|---|---|---|
| lint | `biome check` | `interlocks.lint.tool = "biome" \| "eslint" \| "oxlint"` |
| format | `biome format --check` | same |
| typecheck | `tsc --noEmit` | `interlocks.typecheck.tool = "tsc"` (no alternatives v0) |
| test | auto-detect: `vitest run` > `jest` > `bun test` | `interlocks.test.runner` |
| coverage | runner-native (vitest/jest --coverage / c8) → lcov | `interlocks.coverage.format = "lcov"` |
| acceptance | `cucumber-js` if `features/` present | `interlocks.acceptance.runner` |
| audit | `npm audit --json` (auto-translate for pnpm/yarn/bun) | `interlocks.audit.severity_min` |
| deps | `knip` | `interlocks.deps.tool = "knip"` |
| arch | `dependency-cruiser` | `interlocks.arch.tool = "depcruise"` |
| complexity | `lizard` (cross-language) | `interlocks.complexity.tool` |
| CRAP | derived (lizard CCN + lcov) | `interlocks.crap_max` |
| mutation | `stryker run` | `interlocks.mutation.tool = "stryker"` |

**Real gaps** (no good off-the-shelf v0 answer):

- **behavior-attribution**: the Python product's registry mechanism is AST-and-import-coupled. No JS analog. Out of scope at v0; document explicitly.
- **bundled defaults for biome/vitest/stryker**: the Python product ships `defaults/ruff.toml`, `pyrightconfig.json`, etc. The npm product ships analogous `defaults/biome.json`, `defaults/vitest.config.ts`, `defaults/stryker.conf.json`. Versioned with the package; precedence below project configs.

## Configuration

Single source: `package.json` under an `"interlocks"` key. Sidecar `.interlocks.json` allowed if user hates `package.json` bloat. No new config language.

Precedence (parallel to Python product):

```
CLI flag  >  package.json#interlocks  >  .interlocks.json  >  bundled default
```

Project's own tool configs (`biome.json`, `tsconfig.json`, `vitest.config.ts`, `.stryker.conf.json`) replace the bundled default for that tool. interlocks never silently overrides a tool's own config.

Threshold keys (numeric, language-neutral):

```jsonc
{
  "interlocks": {
    "preset": "baseline",                  // baseline | strict | legacy
    "coverage_min": 80,
    "crap_max": 30,
    "complexity_max_ccn": 10,
    "mutation_min_score": 60,
    "mutation_ci_mode": "incremental",     // off | incremental | full
    "audit_severity_min": "high",
    "changed_ref": "origin/main",
    "pr_ci_runtime_budget_seconds": 600
  }
}
```

## Architecture

Single npm package, single binary. Mirror the Python layout:

```
packages/interlocks/
  src/
    cli.ts                  # entrypoint + crash boundary (one place, parallel to interlocks/cli.py::main)
    config.ts               # threshold resolver
    runner.ts               # Task abstraction (Task = label + argv + parser + threshold)
    metrics/
      lcov.ts               # lcov parser
      lizard.ts             # CCN parser
      crap.ts               # composition
    stages/
      check.ts ci.ts pre-commit.ts
    tasks/
      lint.ts format.ts typecheck.ts test.ts coverage.ts
      acceptance.ts audit.ts deps.ts arch.ts complexity.ts mutation.ts
    detect/
      package-manager.ts    # npm | pnpm | yarn | bun
      runner.ts             # vitest | jest | bun:test
    defaults/
      biome.json vitest.config.ts stryker.conf.json depcruise.config.cjs
    crash/
      boundary.ts payload.ts transport.ts   # SAME invariants as Python: no SDK, no background network
  bin/interlocks
  package.json
```

Single binary. Reject "two parallel CLIs" (same reasoning as the Python architecture review).

## Invariants (carry over from Python)

These are non-negotiable and mirror the Python product:

1. **Single crash boundary.** `cli.ts` is the only `try/catch` around task dispatch. No `process.on('uncaughtException')` second boundary.
2. **No background network from `crash/`.** `crash/transport.ts` renders a payload to a URL for browser handoff. No `fetch`, no `node:http`, no `node:net`, no telemetry SDKs (`@sentry/*`, `posthog-js`, etc.) anywhere under `src/crash/`. A negative test enforces this via static import scan, parallel to `tests/test_crash_transport.py`.
3. **Allowlist payload fields.** `crash/payload.ts` maintains an explicit allowlist; widening it requires updating the security doc and the negative test.
4. **Threshold resolution precedence is immutable** (CLI > package.json#interlocks > .interlocks.json > bundled default). No tool's own config silently overrides interlocks' threshold knobs.
5. **`tasks/*` never imports `stages/*`.** Layer boundary enforced by an import-linter analog (e.g., `dependency-cruiser` rule) in this very project's CI.
6. **Single project root per invocation.** `find_project_root` walks up to the nearest `package.json`. Polyglot repos are handled by running interlocks twice (once for Python root, once for JS root), not by branching internally.

## Failure modes (named, not solved)

| Mode | Mitigation |
|---|---|
| Native deps under bun runtime | Pre-flight check; warn before `bun test`; suggest `node` fallback. |
| Monorepo workspaces (pnpm/yarn/bun) | v0: run per-package, no aggregation. v0.2: `--workspaces` flag. |
| Coverage format drift across runners | Normalize via lcov. Refuse to gate (warn) if parser version mismatches; never fail-open. |
| `npm audit` JSON schema changes | Pin parser; integration-test against captured fixtures; degrade to advisory if format unknown. |
| tsc memory blowup on large repos | Honor `--incremental`; document. |
| Mutation runtime explosion | Same as Python: enforce `mutation_max_runtime`, report partial. |
| Two interlocks instances (Python+JS) in polyglot repo | Crash cache namespaced by `(root, lang)`. |

## Success criteria (6 months post-GA)

Concrete, falsifiable. Vanity metrics excluded.

- ≥30 weekly-active repos running `interlocks ci` or the Action with a real failure history (not just install).
- ≥10 of those repos also run the Python interlocks (proves polyglot wedge).
- Median CI runtime under `pr_ci_runtime_budget_seconds` (default 600s) on a 50k-LOC reference repo.
- Issue tracker shows ≥3 distinct external contributors filing real bugs (not "thanks for the project" stars).

If after 6 months of GA the repo count is <10, **sunset** without apology. Same bar STRATEGY.md applies to the Python product.

## Out-of-scope, period

- Reinventing biome/stryker/etc.
- Replacing eslint plugins with first-party rules.
- Hosted control plane (deferred, not denied — but not v0).
- Cross-language CRAP comparison.
- Replacing the Python product. Both ship independently. No shared binary, no shared release.

## Open questions

1. **Brand**: `@interlocks/cli`, `interlocks-js`, or a different name entirely? Sharing the name reuses Python interlocks' (currently small) brand equity but invites "is this the same product?" confusion.
2. **Agent-governance angle**: STRATEGY.md treats this as the next commercial wedge for the Python product. Does v0 of npm interlocks ship with that framing, or stay narrowly "JS quality gate composer" until pull arrives?
3. **Polyglot UX**: in a Python+TS monorepo, do users want one command (`il check --all`) that runs both interlocks binaries? If yes, that's a third (small) artifact: a polyglot orchestrator. Not v0.
4. **TypeScript dogfood**: this project would itself be written in TS. That solves the dogfood collapse for the JS side but does not solve cross-product testing — the Python interlocks cannot dogfood the npm product, and vice versa. Accept the asymmetry.
5. **Stryker license / runtime cost**: stryker mutation runs are slow. Is the default `mutation_ci_mode = "incremental"` acceptable, or do we need `"off"` as default to avoid scaring first-run users?

## Build Gate

This spec is **not** approval to start coding. Per the prior strategic review and STRATEGY.md's own bar, two conditions must hold first:

1. The Python `interlocks` has ≥10 active adopters running `il ci` weekly (current count: not yet measured publicly; assume below threshold).
2. ≥3 of those adopters explicitly request a JS/TS sibling for a polyglot repo they already use the Python product on. **Pull, not push.**

If both hold, this spec is the starting point. If neither holds, this spec is shelved and revisited quarterly.

## Provenance

This spec was produced after a structured team review (strategist + architect + skeptic). The skeptic's verdict was "kill" given the current state of Python adoption; the architect's `Toolchain`-extraction recommendation is captured here and would be done **inside** the Python product as cohesion work regardless of whether this npm sibling ships. Verified facts about the JS toolchain (biome scope, stryker scope, cucumber-js status, CRAP tooling gaps) sourced from biomejs.dev, stryker-mutator.io, cucumber.io, and GitHub repository discovery on 2026-05-05.
