# Simplify the interlocks CLI Around Workflow Commands

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository follows the ExecPlan rules in `~/.codex/PLANS.md`. This file is self-contained so a contributor can restart from this document and the current working tree without prior conversation context.

## Purpose / Big Picture

After this change, a person using interlocks will see one small workflow-oriented command surface instead of a long list of wrapped tools. The core product promise is one deterministic Python quality loop for local edits, hooks, CI, and agent-authored pull requests. The CLI should match that promise by making `doctor`, `setup`, `check`, `ci`, and `nightly` feel primary, while still allowing direct debugging through `interlocks gate <name>`.

The observable result is that `interlocks help` and `interlocks help --json` list only primary workflow commands. Direct gates run as nested commands, for example `interlocks gate lint`, `interlocks gate coverage --min=80`, and `interlocks gate acceptance`. Fix helpers run under `interlocks fix`, setup helpers use `interlocks setup --hooks`, `interlocks setup --agents`, or `interlocks setup --skill`, and scaffold helpers use `interlocks init --acceptance` or `interlocks init --properties`. Old top-level tool command names are intentionally removed because there are no external users to preserve.

## Progress

- [x] (2026-06-02T11:23Z) Read `~/.codex/PLANS.md`, current `AGENTS.md`, `interlocks/cli.py`, `interlocks/command_docs.py`, README command map, and current live help JSON to establish the starting CLI shape.
- [x] (2026-06-02T11:23Z) Defined the target command shape and no-backwards-compatibility constraint in this ExecPlan.
- [x] (2026-06-02T13:06Z) Refactored command documentation and dispatcher so top-level commands are primary workflow commands plus `gate`, `fix`, `setup`, and `init`.
- [x] (2026-06-02T13:06Z) Updated task output strings, default templates, docs, and tests to reference the new nested command names.
- [x] (2026-06-02T13:06Z) Ran focused CLI/task tests and `uv run interlocks check`; searched for stale removed top-level commands.

## Surprises & Discoveries

- Observation: The CLI already hides some complexity in default help, but advanced help and the registered command set still expose 47 commands.
  Evidence: `uv run interlocks help --advanced --json` returned `Tasks`, `Stages`, `Reports`, `Utility`, and `Other` groups with tool and integration plumbing commands.

## Decision Log

- Decision: Keep `doctor`, `setup`, `check`, `ci`, `nightly`, `config`, `explain`, `clean`, `version`, `warm`, and `help` as primary top-level commands.
  Rationale: These are workflows, project inspection commands, or universal utility commands that support the product goal rather than single wrapped tools.
  Date/Author: 2026-06-02 / Codex.

- Decision: Move direct quality gates under `interlocks gate <name>`.
  Rationale: Debugging a failing gate remains precise, but users do not need to learn a dozen peer commands before understanding the quality loop.
  Date/Author: 2026-06-02 / Codex.

- Decision: Move fix-plan, fix-replay, fix-optimize, fix-annotate, fix-metrics, and fix-rule under `interlocks fix <subcommand>`, while bare `interlocks fix` continues to run the ruff auto-fix gate.
  Rationale: These commands are one feature family and should not compete with workflow commands.
  Date/Author: 2026-06-02 / Codex.

- Decision: Move `agents`, `setup-skill`, and hook installation under `interlocks setup` flags; move acceptance and property scaffolding under `interlocks init` flags.
  Rationale: They are setup/scaffold modes, not independent user goals.
  Date/Author: 2026-06-02 / Codex.

- Decision: Remove old top-level command names instead of compatibility aliases.
  Rationale: The user explicitly said no backwards compatibility is needed because there are no users yet.
  Date/Author: 2026-06-02 / Codex.

## Outcomes & Retrospective

The CLI now presents workflow-first top-level help. Default help shows `doctor`, `setup`, `check`, `ci`, `nightly`, `gate`, `fix`, `init`, `config`, `presets`, `explain`, `clean`, and `version`. Advanced help exposes direct quality gates under `gate <name>`, fix helpers under `fix <subcommand>`, and installed hook entrypoints under `hook <subcommand>`.

Old top-level gate and helper commands were removed instead of kept as aliases. For example, `interlocks coverage --help` now fails with `Unknown command: coverage`, while `interlocks gate coverage --help` succeeds. The only compatibility alias kept is `fix unblock` for `fix optimize`, because it remains a semantic alias inside the fix family rather than an old top-level route.

Setup and scaffold helpers are now modes of their owning workflows: `setup --hooks`, `setup --agents`, `setup --skill`, `init --acceptance`, and `init --properties`. Hook installation now writes nested hook commands.

Behavior-attribution freshness now includes the behavior registry file itself, so changing declared behavior symbols forces evidence regeneration instead of reusing stale attribution evidence.

## Context and Orientation

`interlocks/cli.py` is the CLI entrypoint. It imports each command handler, maps command names to callables in `TASK_HANDLERS`, derives the public `TASKS` map from the documentation registry, validates flags, runs preflight checks, and invokes the handler. A handler is a Python function such as `cmd_check` or `cmd_coverage`.

`interlocks/command_docs.py` is the structured command documentation registry. It defines `CommandDoc` and `FlagSpec`, declares one document per command, declares command groups, and validates unknown flags by matching CLI tokens against a command's declared flags. This registry is the source for `interlocks help`, `interlocks help --json`, and `interlocks explain`.

`interlocks/tasks/` contains single gate and utility command handlers, such as `coverage.py`, `audit.py`, `properties.py`, and `fix_rule.py`. `interlocks/stages/` contains workflow stages such as `check.py`, `ci.py`, `nightly.py`, and hook stages.

A direct gate means a single wrapped quality tool or focused quality check, for example lint, typecheck, coverage, audit, architecture checks, acceptance tests, property tests, CRAP, complexity, or mutation. A workflow command means a user-facing sequence or project operation, for example check, CI, setup, doctor, or nightly.

## Plan of Work

First, change the documentation registry to express the new command surface. The registry should contain top-level command documents for `gate`, `fix`, `setup`, and `init` with their nested usage forms. Old direct gate documents can be kept as source data only if the dispatcher and help payloads expose them through the nested parent command, but old names must not remain valid top-level commands.

Second, refactor `interlocks/cli.py` so `main()` resolves nested commands. `interlocks gate coverage --min=80` must dispatch to the existing `cmd_coverage` handler and validate coverage flags. `interlocks fix rule --rule=I001` must dispatch to `cmd_fix_rule`, and bare `interlocks fix` must continue to dispatch to `cmd_fix`. `interlocks setup --check` must keep current setup behavior, while `interlocks setup --hooks`, `interlocks setup --agents`, and `interlocks setup --skill` dispatch to existing handlers. `interlocks init --acceptance` and `interlocks init --properties` dispatch to existing scaffold handlers, while bare `interlocks init` keeps current greenfield scaffold behavior.

Third, update user-facing strings and repository docs so recommended commands use the new forms. Examples include `interlocks gate test`, `interlocks gate coverage`, `interlocks gate acceptance`, `interlocks init --acceptance`, `interlocks init --properties`, `interlocks fix optimize`, and `interlocks fix rule`.

Fourth, update tests. Existing behavior tests should now exercise nested commands. Tests that assert old top-level commands exist should be rewritten to assert the simplified surface and rejection of removed names.

Fifth, validate with focused tests, then run the primary repository check. Search for stale command strings that describe removed top-level commands in user-facing docs, templates, and tests.

## Concrete Steps

From `/Users/juan/Code/interlocks`, run:

    uv run interlocks help --json
    uv run interlocks help --advanced --json
    uv run interlocks gate lint --help
    uv run interlocks gate coverage --help
    uv run interlocks fix rule --help
    uv run interlocks setup --hooks --help
    uv run interlocks init --acceptance --help

After edits, run focused tests:

    uv run pytest -q tests/test_cli.py
    uv run pytest -q tests/features/interlock_cli.feature tests/features/interlock_tasks.feature tests/features/interlock_meta.feature tests/features/interlock_fix.feature

Then run the repository post-edit workflow:

    uv run interlocks check

## Validation and Acceptance

The work is complete when `interlocks help --json` shows a small set of top-level commands centered on workflows, not individual gates. It must include `gate`, `fix`, `setup`, and `init`, and it must not include old top-level names such as `lint`, `coverage`, `acceptance`, `fix-rule`, `fix-plan`, `setup-hooks`, `setup-skill`, `agents`, `init-acceptance`, or `init-properties`.

Nested and mode-specific help must work. `interlocks gate coverage --help` should show coverage usage and flags. `interlocks fix rule --help` should show rule-fix usage and flags. `interlocks init --acceptance --help` should show acceptance scaffold usage.

Nested command execution must work. At minimum, `interlocks gate lint --json`, `interlocks gate test --json`, or focused test substitutes should prove nested gate dispatch invokes the existing handlers. Existing workflow commands such as `interlocks check`, `interlocks ci`, and `interlocks setup --check` must still resolve.

Old top-level command names must fail as unknown commands. For example, `interlocks coverage --help` should fail, while `interlocks gate coverage --help` succeeds.

## Idempotence and Recovery

The refactor edits Python source, docs, templates, and tests. Re-running tests and help commands is safe. If a nested command dispatch bug appears, inspect `interlocks/cli.py` resolution before changing task modules. Task modules should remain mostly intact because the refactor changes command routing, not the underlying gates.

If broad docs or tests still contain old command strings, update them only when they are user-facing examples or assertions for CLI behavior. Internal historical references in changelogs or comments can remain if they do not teach users to invoke removed commands.

## Artifacts and Notes

Initial evidence:

    uv run interlocks help --json
    returned Start here, Common gates, and Project groups, including 21 default commands.

    uv run interlocks help --advanced --json
    returned 47 registered commands across Tasks, Stages, Reports, Utility, and Other.

Final validation:

    uv run interlocks gate behavior-attribution
    passed.

    uv run pytest -q tests/test_behavior_attribution.py tests/test_behavior_attribution_trace.py tests/test_behavior_attribution_validate.py tests/test_behavior_attribution_freshness.py tests/test_behavior_attribution_standalone.py tests/test_cli.py -x
    passed, 155 tests.

    uv run pytest -q properties/test_behavior_attribution_properties.py -x
    passed, 33 tests.

    uv run interlocks check
    passed.

    git diff --check
    passed.

    uv run python -m compileall -q interlocks tests tools
    passed.

    uvx --from ruff==0.15.12 --index-strategy first-index ruff check interlocks tests tools --output-format=concise
    passed.

    uv run interlocks help --json
    showed the workflow-first default command groups.

    uv run interlocks help --advanced --json
    showed nested `gate`, `fix`, and `hook` command families.

    uv run interlocks gate coverage --help
    passed.

    uv run interlocks coverage --help
    failed with `Unknown command: coverage`, as intended.

    Stale-route `rg` sweeps across README, docs, interlocks, tests, tools, properties, .github, pyproject.toml, and action.yml found no old public command strings except this ExecPlan's intentional negative example.

## Interfaces and Dependencies

No new external dependencies are required. Use the existing Python standard library-only dispatcher style. Existing handlers keep their function signatures. New dispatcher helpers in `interlocks/cli.py` should return a resolved task identity that can drive flag validation, preflight, crash boundaries, and command help without importing new frameworks.
