# Architecture Fidelity Review (vs `architecture.md`)

Verdict legend: **ACCEPTABLE** (semantic equivalence or improvement) · **CONCERN** (latent risk or interface drift) · **REGRESSION** (contract violated).

## 1. `SkipPolicy` (vs `SkipRegistry`) — **ACCEPTABLE**

`skip.py:23-29` ships a frozen dataclass with `frozenset[str]` + source. "Skip set frozen before first Task executes" is now structural — immutability enforced by type, not convention. Value-object naming is more accurate than "registry". No behavior diff.

## 2. `ToolConfigSource` / `tool_config_source` (vs `provenance_probe`) — **ACCEPTABLE (improvement)**

`defaults_path.py:28-88` — dataclass is the single decider; `config_flag_if_absent` (91-115) now calls it and reads `is_bundled`. Coupling goal ("decide + render-source behind one API") achieved. Dataclass carries `bundled_path` + `flag` so `config show --bundled-only` renders without re-deriving. Single source of truth preserved.

## 3. `config show` inlined under `cmd_config` — **CONCERN (interface narrower than spec)**

Inlining is fine (`tasks/config.py:60-184`); contract is partly broken:

- Header `[tool] (<source>)` — DONE via `ui.command_banner`.
- `<source>` taxonomy `bundled` | `project: pyproject.toml [tool.X]` | `project: <sidecar>` — DONE via `project_config_source`.
- `--bundled-only`, `--json` — DONE.
- **Body is metadata-only**: rows are `tool/source/path/bundled_path/flag`. Spec said *"resolved body — TOML for ruff/coverage/importlinter, JSON for pyright"*; file CONTENT is never read. JTBD "show me bundled `select`/`ignore`" still needs `cat $(interlocks config show ruff --json | jq -r .path)`.
- JSON schema drift: spec `{tool, source, path, config}`; ships `{tool, source, path, bundled_path, flag}`. **No `config` key.**

Either ship body-render in a follow-up or update FAQ to say `config show` reports provenance only and points to the path. Current state is internally consistent but undersells the "make bundled rules visible" promise from ground-truth Q1.

## 4. Skip validation gate-only — **ACCEPTABLE**

`SKIP_LABELS` (14 gate labels) rejects stages. Architecture.md §3 prescribed `TASKS.keys() ∪ STAGE_LABELS`, but `INTERLOCKS_SKIP=ci interlocks ci` is nonsense. Stage-level disabling belongs to a separate surface, not `skip`. Capability loss is theoretical. Error path (`skip.py:117-119`) lists known labels — typos get discoverable suggestions. Document the boundary in FAQ so users don't assume `--skip=ci` works.

## 5. `crash/payload.py` allowlist NOT updated — **CONCERN (latent)**

Confirmed: `payload.py:83-96` ships 12 keys; no `skip`. `CrashBoundary(subcommand=task_name)` (cli.py:394) never receives the policy. Architecture.md invariant is **moot under current wiring** — skip never enters payload.

Latent risk: skip-induced crash modes (e.g. `--skip=coverage` then `crap` reads missing `coverage.xml` → crash) produce payloads with no signal a gate was skipped. Fingerprint dedupes "user skipped X" and "X genuinely broke" together, muddying triage.

Mitigation: add `"skip": sorted(policy.labels)` to `build_payload`, plumb `policy` through `CrashBoundary.__init__`, update `ALLOWLIST_KEYS`. Recommended now while surface is small.

## 6. `action.yml` pinned `@v1` — **CONCERN (install-blocking)**

`defaults/github_workflow.yml:13` references `0xjgv/interlocks@v1`. No `v1` tag/branch exists (repo at `0.1.6`). First user to run `setup --ci=github` hits a 404 from Actions resolver. Plan said `@v0.1`. Either (a) cut a floating `v1` branch at first release, (b) pin `@v0` (pre-1.0 norm), or (c) `@v0.1.6` with bump note. Block before any user-visible release.

## 7. Bundled `pyrightconfig.json` lacks `pythonVersion` — **ACCEPTABLE**

File never had it. basedpyright falls back to project pyproject, then interpreter. A project with neither override gets interpreter-version semantics — same as before the floor change. No regression. Bundled file's job is to mute noisy `report*` flags, not pin a target.

## 8. CI/nightly skip banner — **ACCEPTABLE**

`ci.py:42-43`, `nightly.py:20-21`, `check.py:70`, `pre_commit.py:29` all call `maybe_print_skip_banner` right after `ui.banner(cfg)`. Suppressed under `ui.is_quiet()`. Spec satisfied.

## Crash-boundary contract — **PRESERVED**

`cli.py:392-397`: `validate_cli_skip() → preflight(task_name) → CrashBoundary(...)`. Skip-arg validation runs OUTSIDE the boundary; typo'd `--skip=lin` exits 2 via stderr without invoking the crash reporter (matches CLAUDE.md I6). Order is `validate → preflight → boundary`, both pre-boundary; contract holds.

## New architectural risks

- **Skip × `--changed` interaction unspecified.** `check.py` consults both; document order: skip wins (label-level) before scope (file-level).
- **Inline-subcommand drift.** `cmd_config` parses `args[0] == "show"`; `cmd_setup` parses `--ci=github`. Two ad-hoc dispatchers; before a third lands, extract a `subcommand(args, table)` helper.
