# QA Evaluation — Acceptance Criteria vs Shipped Code

Evidence-based verdict per criterion. **PASS** / **FAIL** / **NOT-IMPL** / **NEEDS-MIGRATION** (works; coverage/format off-spec).

---

## B1 — FAQ skim test

| Criterion | Verdict | Evidence |
|---|---|---|
| ≥4 entries | PASS | 6 entries. |
| ≤120 words/entry | PASS | 284/6 ≈ 47. |
| 4 JTBDs covered | PASS | style / skip / setup / Python all present. |
| Heading regex `^\*\*Q:` | NEEDS-MIGRATION | Uses `### Question`. Spec or README converges. |
| Blob URL rot-guard test | NOT-IMPL | `tests/test_readme_faq.py` absent. |

## B2 — Python 3.11 floor

| Criterion | Verdict | Evidence |
|---|---|---|
| `python3.11 -m compileall interlocks/` | PASS | exit 0. |
| CI matrix 3.11/3.12/3.13 | PASS | `ci.yml:15`. |
| `requires-python>=3.11` | PASS | `pyproject.toml:6`. |
| `defaults/ruff.toml target-version=py311` | PASS | line 8. |
| `defaults/pyrightconfig.json pythonVersion=3.11` | **FAIL** | key absent; `grep pythonVersion` empty. |
| 3.10 install fails | PASS (by manifest) | metadata-enforced; not run live. |

## B3 — `config show <tool>`

| Criterion | Verdict | Evidence |
|---|---|---|
| Command exists | PASS | live run works. |
| Source label | PASS | "source: project: pyproject.toml [tool.ruff]". |
| `--bundled-only`, `--json` | PASS | per inventory. |
| Unknown tool → exit 2 + suggestion | NOT-VERIFIED | covered in `test_config.py`. |
| Gherkin in `tests/features/` | NOT-IMPL | no hits in feature file. |
| `tests/tasks/test_config_show.py` | NEEDS-MIGRATION | absent; coverage in `test_config.py:140-182`. |
| Header `[ruff] (bundled)` literal | NEEDS-MIGRATION | output uses key/value rows; functional, not literal. |

## B4 — Setup ergonomics + v2 + banner

| Criterion | Verdict | Evidence |
|---|---|---|
| Next-Steps reorder | PASS | `tasks/setup.py:77-82`. |
| Agents-block v2 idempotency | PARTIAL | block 18/26 lines; missing override-precedence + escalation. |
| Maturity banner | **NOT-IMPL** | grep `maturity\|\.seen\|early release` in `interlocks/` = 0. |
| `.interlocks/.seen` | **NOT-IMPL** | absent. |
| `tests/test_maturity_banner.py` | NOT-IMPL | absent. |

## B5 — `setup --ci=github`

| Criterion | Verdict | Evidence |
|---|---|---|
| Writes workflow | PASS | `defaults/github_workflow.yml` shipped. |
| `--check --ci=github` row | PASS | live: `[github ci] installed` exit 0. |
| Idempotent rerun | NOT-VERIFIED | mtime not checked live. |
| Refuse-foreign without `--force` | **FAIL** | `fail_skip` on conflict but no `--force` override flag. |
| Gherkin scenario | NOT-IMPL | absent. |

## B6 — Skip API

| Criterion | Verdict | Evidence |
|---|---|---|
| Precedence CLI>env>pyproject | PASS | `skip.py:32-41` + units in `test_cli.py`, `test_config.py`. |
| Typo exits 2 | PASS | `--skip=mutaton` → exit 2. |
| Suggestion "Did you mean…" | **FAIL** | message lists `known: a,b,c`; no fuzzy match. |
| Stage-label skip (`--skip=check`) | **FAIL** | exit 2 "unknown"; spec required `TASKS ∪ STAGE_LABELS`. |
| Skipped task absent from `_RESULTS` | PASS | `runner.py:212-215,232-236`. |
| Crash payload `"skip"` allowlist | **FAIL** | grep `skip` in `crash/payload.py` = 0. |
| Negative env-leak test for skip | NOT-IMPL | generic env-leak test exists; no skip-specific. |
| CI/nightly banner | PASS | live: `skips active (cli): mutation`. |
| Gherkin scenarios | NOT-IMPL | absent. |
| `tests/test_skip.py` | NEEDS-MIGRATION | absent; coverage in `test_cli.py` + `test_config.py`. |

## Onboarding success metric

| Criterion | Verdict | Evidence |
|---|---|---|
| `tests/e2e/test_agent_onboarding.sh` (≤5 cmds, final `check` exit 0) | NOT-IMPL | File absent. |

---

## Shipping Blockers

1. **B6 crash-payload `"skip"` allowlist + negative test absent.** Plan §B6 mandated both. Without the allowlist + a pinning negative test, a future contributor wiring `os.environ["INTERLOCKS_SKIP"]` into invocation context can leak. Architecturally defensible to keep skip OUT of the payload — but that decision must be pinned by a test asserting absence. Hard blocker per architecture invariant.
2. **B6 stage-label skip rejected.** `--skip=check` exits 2; spec mandated `TASKS ∪ STAGE_LABELS`. User-visible regression.
3. **B6 typo suggestion absent.** Highest-traffic error path; "Did you mean 'mutation'?" missing.

## Polish Gaps

- **B2** `defaults/pyrightconfig.json` lacks `pythonVersion="3.11"` (1-line).
- **B4** maturity banner + `.seen` absent.
- **B5** no `--force` for foreign-workflow conflict.
- Gherkin migration: `config show`, `--ci=github`, `--skip` not in `tests/features/interlock_cli.feature` (CLAUDE.md mandates this for new subcommands).
- **B1** FAQ uses `### Q` heading style; converge spec or README.
- CHANGELOG + 0.2.0 bump pending; `[Unreleased]` only has typecheck fix.
- Onboarding E2E script absent.

---

## Merge today: **NO**

Top-3 critical fixes:

1. **Pin `"skip"` decision in crash payload.** Either add to `crash/payload.py` allowlist as `list[str]`, OR add a negative test in `tests/test_crash_payload.py` asserting `skip` is NOT in the payload (whichever path the architect picks — but pinned by test, same commit).
2. **Extend `config.SKIP_LABELS` with `{"check","ci","nightly","pre-commit"}`** so stage-level skip works. Add unit + Gherkin.
3. **Fuzzy suggestion for skip typo** — `difflib.get_close_matches(label, SKIP_LABELS, n=1, cutoff=0.6)` → "Did you mean 'mutation'?". Trivial; user-visible.

Polish (banner, pyright default, `--force`, Gherkin migration, CHANGELOG, version bump) can land in a follow-up PR same release window.
