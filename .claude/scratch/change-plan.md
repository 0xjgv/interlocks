# Engineering Change Plan — interlocks adoption fixes

Solo-maintainer ship order. Each batch = one PR. **S** ≤ 30 min · **M** ≤ 2 h · **L** ≤ 1 d.

---

## Batch 1 — README FAQ (S, no risk)

Insert `## FAQ` (8 entries from `jtbd-and-faq.md`) into `README.md` between line 229 and 230 (`## Stages`). +110 lines, doc-only. Blob URLs without line anchors. No tests; risk: link rot (mitigated).

---

## Batch 2 — Python floor 3.13 → 3.11 (S–M, low risk; removes install gate)

Per architecture §1: rewrite two PEP 695 generics; align bundled defaults to `py311`.

| # | File | Change | LOE |
|---|---|---|---|
| 1 | `pyproject.toml:6,12,183` | `requires-python=">=3.11"`; classifiers; `pythonVersion="3.11"` | S |
| 2 | `interlocks/hook_setup.py:14` | `[T:(dict[...],list[...])]` → module-level `TypeVar` | S |
| 3 | `interlocks/config.py:684` | `[T]` → module-level `TypeVar` | S |
| 4 | `interlocks/defaults/ruff.toml:8` | `target-version="py311"` | S |
| 5 | `interlocks/defaults/pyrightconfig.json` | `pythonVersion="3.11"` | S |
| 6 | `interlocks/defaults/scaffold_pyproject.toml:4` | `>=3.11` | S |
| 7 | `.github/workflows/ci.yml:15` | matrix `["3.11","3.12","3.13"]` | S |
| 8 | `AGENTS.md:24`, `README.md` | Audit `3.13` mentions | S |

`nightly.yml`/`release.yml` stay on 3.13 (host runtime). **Blast radius**: ruff `UP` rules may fire on rewritten generics — fix or `# noqa: UP040`. No new tests. **Risks**: hidden 3.13 stdlib (Low/High → 3.11 matrix); `UP` fires (Med/Low → noqa).

---

## Batch 3 — `interlocks config show <tool>` (M, additive)

| File | Change | LOE |
|---|---|---|
| `interlocks/tasks/config_show.py` (NEW) | `cmd_config_show()`. Parse `<tool>`, `--bundled-only`, `--json`. Render `[tool] (<source>)` + body. Catch `tomllib.TOMLDecodeError` → `{"error":...}`. | M |
| `interlocks/defaults_path.py` | Add `provenance_probe(cfg, *, section, sidecars) -> tuple[Path, str]`; refactor `config_flag_if_absent` to call it. | S |
| `interlocks/cli.py:367` | Register `"config-show"` in TASK_GROUPS Config group. | S |
| `interlocks/tasks/config.py` | "Next steps" pointer to `config-show`. | S |
| `tests/test_defaults_path.py` | `provenance_probe` × 4 cases (bundled / sidecar / pyproject / both). | M |
| `tests/tasks/test_config_show.py` (NEW) | Source label; `--json` keys; unknown → exit 2. | M |
| `tests/features/interlock_cli.feature` | Scenario: `interlocks config-show ruff` exits 0, prints `[ruff] (bundled)`. | S |

Whitelist: `ruff`, `pyright`, `coverage`, `importlinter`. **Blast**: `cmd_help()` regenerates → smoke snapshot tests update. **Risks**: broken pyproject (Low/Med → `TOMLDecodeError` catch); typo'd tool (Med/Low → whitelist + suggestion).

---

## Batch 4 — Setup ergonomics + agents-block v2 + maturity banner (M, low risk)

| File | Change | LOE |
|---|---|---|
| `interlocks/tasks/setup.py:52-55` | Swap order: `interlocks check` first, `doctor` second. | S |
| `interlocks/defaults/agents_block.md` | 13-line block → 26-line v2 (blocking matrix + override precedence + escalation list per `onboarding-flow.md` §3). | S |
| `AGENTS.md:24` | Update Python target; mirror v2 escalation rules. | S |
| `interlocks/cli.py::main` | Insert `_maybe_print_maturity_banner(project_root)` after `preflight`, before `CrashBoundary`. | S |
| `interlocks/cli.py` (helper) | Skip if `--quiet` / non-TTY / `CI` env / `<root>/.interlocks/.seen` exists; else print 3-line banner; create marker. | M |
| `tests/stages/test_setup_hooks.py` | Regenerate any byte-snapshot of agents block. | S |
| `tests/features/interlock_agents.feature:36` | Re-validate idempotency guard (`text_references_check_stage` matches v2). | S |
| `tests/test_cli.py` (or new `test_maturity_banner.py`) | First-run emit; suppression on `.seen`/`--quiet`/`CI`. | M |

V2 still contains literal `interlocks check` → `text_references_check_stage` still matches → no `interlock_agents.feature` regression. **Risks**: CI log spam (High/Low → suppress on `CI` env); `.seen` perms (Low/Low → `mkdir(exist_ok=True)`).

---

## Batch 5 — `setup --ci=github` writer (M, opt-in)

Wire existing `_CI_WORKFLOW_NEEDLES` detector (`setup_state.py:25-28`) into a writer. Detector stays read-only; new path is opt-in.

| File | Change | LOE |
|---|---|---|
| `interlocks/defaults/ci_workflow.yml` (NEW) | 12-line workflow `uses: <repo>@v0.1` (mirror `interlocks/github_action.py` shape). | S |
| `interlocks/setup_state.py:160` | Add `SetupArtifact("ci workflow", ".github/workflows/interlocks.yml", ci_workflow_present)` to `SETUP_ARTIFACTS`. | S |
| `interlocks/ci_setup.py` (NEW) | `install_ci_workflow(project_root)`: idempotent write; existing-with-needles → `ok(...)`; existing-without → `warn_skip("present, not interlocks-wired")`. | M |
| `interlocks/tasks/setup.py:34-47` | Parse `--ci[=github]`; default `setup` does NOT install CI; when set, append `install_ci_workflow` after `install_skill`. | S |
| `tests/stages/test_setup_hooks.py` | `--ci=github` writes; second run idempotent; `setup --check` row. | M |
| `tests/features/interlock_cli.feature` | Scenario: `setup --ci=github` then `setup --check` exits 0, ci-workflow row "installed". | S |

**Blast**: `setup --check` gains a row → snapshot tests update. **Risks**: action-version drift (Med/Med → tag `v0.1` branch alongside semver); existing non-interlocks workflow at target path (Med/Med → refuse + `--force` hint).

---

## Batch 6 — Skip API (L, ship LAST; touches crash payload)

Per architecture §3: CLI > env > pyproject; strict validation; never reverses failing exit code.

| File | Change | LOE |
|---|---|---|
| `interlocks/skip.py` (NEW) | `SkipRegistry`: frozen `frozenset[str]` + `dict[label, source]`. Validate against `TASKS.keys() ∪ {"check","ci","nightly","pre-commit"}`; unknown → `fail_skip` with suggestion. | M |
| `interlocks/config.py:_resolve_config_table` | Parse `skip: list[str]` from `[tool.interlocks]`; record in `value_sources`. | S |
| `interlocks/cli.py::main` | Parse `--skip=`; read `INTERLOCKS_SKIP`; build `SkipRegistry` BETWEEN `preflight` and `CrashBoundary`. | M |
| `interlocks/runner.py:140-152` | Filter via `SkipRegistry.contains(label)`; emit `warn_skip(f"[{label}] skipped (skip={src})")`. Never enter `_RESULTS`. | M |
| `interlocks/stages/{check,ci,nightly,pre_commit}.py` | Filter task list. CI + nightly: top banner when registry non-empty. | M |
| `interlocks/crash/payload.py` | Extend allowlist with `"skip": list[str]` (validated label set, never values). | S |
| `tests/test_crash_payload.py:29` | Add `"skip"` to `ALLOWLIST_KEYS`; negative test: env values never leak. | S |
| `tests/test_skip.py` (NEW) | Precedence; typo → exit 2; empty registry no-ops. | M |
| `tests/test_runner.py` | Skipped label in stderr, never in `_RESULTS`. | M |
| `tests/features/interlock_cli.feature` | Scenarios: `--skip=mutation` banner+skip; `INTERLOCKS_SKIP=lin` typo → exit 2 + suggestion. | M |
| `interlocks/tasks/config.py` | Surface resolved `skip` + source in "Resolved values". | S |
| `README.md` FAQ entry (b) | Flip `*Planned…*` to active-tense. | S |

**Blast radius**: payload-allowlist test MUST update in same commit (CI fails otherwise). `tests/test_crash_transport.py` no-network introspection unaffected (skip is local). Stage tests gain a no-skip baseline.

**Risks**:
| Risk | L | I | Mitigation |
|---|---|---|---|
| Skip masks failure → green CI hides regression | Med | High | Mandatory banner in `ci`/`nightly` when non-empty. |
| `INTERLOCKS_SKIP` env value leaks into payload | Low | High | Allowlist test pins `skip` as validated `list[str]` only. |
| Crash-boundary contract slip | Low | Critical | Resolution OUTSIDE boundary; bad input via `fail_skip` (pre-boundary). |
| Stage-vs-task label collision (`check`) | Med | Med | Validation uses `TASKS.keys() ∪ STAGE_LABELS`; document `--skip=check` semantics. |

---

## Ship Order

| # | Batch | Risk | LOE | Rationale |
|---|---|---|---|---|
| 1 | README FAQ | None | S | Doc-only; immediate (a) trust win. |
| 2 | Python 3.11 floor | Low | M | Removes install wall blocking everything else. |
| 3 | `config show` | Low | M | Closes (a) opacity; FAQ "Planned" notes converge. |
| 4 | Setup ergonomics + v2 block + banner | Low | M | Pure UX; no invariants touched. |
| 5 | `setup --ci=github` | Med | M | Touches `.github/`; opt-in flag prevents surprise. |
| 6 | Skip API | Med-High | L | Crash-payload + runner + 4 stages. Land after matrix is green on 3.11/3.12/3.13. |

**Critical path** (sequential): 2 → 3 → 6 (skip API depends on label registry; `config show` proves out `provenance_probe` first). Batches 1, 4, 5 parallelize with 2/3.

**Total estimate**: ~3 focused days across 6 PRs (1: 1 h · 2: 2 h · 3: 4 h · 4: 3 h · 5: 4 h · 6: 6–8 h).
