# Acceptance Criteria — interlocks adoption fixes

Per-batch G/W/T + gates. Tests writable directly.

---

## Batch 1 — README FAQ (skim test)

`tests/test_readme_faq.py` (new), runs in test stage. Parse the FAQ section between `## FAQ` and the next `## `:

- ≥4 entries match `^\*\*Q:`; each (Q+A, code fences excluded) ≤ **120 words** (~30s @ 240wpm).
- ≥1 headline matches each of `/styling.+rules|defaults/i`, `/skip|relax/i`, `/setup.+wire/i`, `/3\.13|python.+floor/i` (4 JTBDs).
- Every blob URL → existing file under `interlocks/`, no `#L` anchor (rot guard).

---

## Batch 2 — Python 3.11 floor

CI matrix required jobs (branch protection): `test (3.11)`, `test (3.12)`, `test (3.13)`.

- 3.11 venv: `pip install interlocks` → exit 0; `python -c "import interlocks"` → exit 0.
- Project checkout on 3.11: `interlocks check` → exit 0 (self-dogfood).
- `python3.11 -m compileall interlocks/` → exit 0 (rewritten generics in `hook_setup.py:14`, `config.py:684`).
- 3.10 venv: `pip install interlocks` → exit≠0 with `requires-python` message (floor enforced; not lower).
- **Boundary:** `defaults/ruff.toml` `target-version="py311"`; `defaults/pyrightconfig.json` `pythonVersion="3.11"`.
- **Regression:** `nightly.yml`, `release.yml` host runtime stays 3.13 (PR-diff assert).

---

## Batch 3 — `interlocks config show <tool>`

Append to `tests/features/interlock_cli.feature`:

```gherkin
Scenario: bundled when no project override
  Given no [tool.ruff] and no ruff.toml sidecar
  When I run "interlocks config-show ruff"
  Then exit 0; stdout starts with "[ruff] (bundled)"
  And stdout contains "target-version = \"py311\""

Scenario: pyproject override
  Given [tool.ruff] in pyproject.toml
  When I run "interlocks config-show ruff"
  Then stdout contains "[ruff] (project: pyproject.toml [tool.ruff])"

Scenario: sidecar override
  Given a ruff.toml sidecar
  When I run "interlocks config-show ruff"
  Then stdout contains "[ruff] (project: ruff.toml)"

Scenario: --json schema is stable
  When I run "interlocks config-show ruff --json"
  Then exit 0; stdout is JSON with keys "tool","source","path","config"

Scenario: unknown tool exits 2 with suggestion
  When I run "interlocks config-show ruffy"
  Then exit 2
  And stderr contains "unknown tool 'ruffy'" and "Did you mean 'ruff'?"

Scenario: malformed pyproject doesn't crash render
  Given malformed [tool.ruff]
  When I run "interlocks config-show ruff --json"
  Then exit 1; stdout is JSON containing key "error"
```

Snapshot fixtures: `tests/fixtures/config_show/ruff.{bundled,pyproject,sidecar}.txt`.

---

## Batch 4 — Setup ergonomics + v2 block + maturity banner

**Banner (`tests/test_maturity_banner.py`):** show iff first run AND TTY AND no `CI=true` AND no `.interlocks/.seen` AND no `--quiet`. On show: 3-line banner to stderr, `.seen` created. On any suppress condition: stderr lacks `early release` substring. Test all 5 suppress conditions independently.

**Agents-block v2 idempotency:** `AGENTS.md` already contains v2 block → `interlocks setup` leaves size delta = 0; `interlocks check` substring present exactly once. `tests/features/interlock_agents.feature:36` still passes (v2 contains literal `interlocks check`).

**Next Steps reorder:** in `interlocks setup` stdout, line index of `interlocks check` < line index of `doctor`.

---

## Batch 5 — `setup --ci=github`

```gherkin
Scenario: --ci=github writes idempotently
  Given .github/workflows/ exists w/o interlocks workflow
  When I run "interlocks setup --ci=github"
  Then exit 0; ".github/workflows/interlocks.yml" exists
  When I run it again
  Then exit 0; mtime unchanged; stdout contains "✓ already wired"

Scenario: setup --check reports new row
  Given interlocks.yml exists with interlocks needles
  When I run "interlocks setup --check"
  Then exit 0; stdout matches /ci workflow.+installed/

Scenario: refuse foreign workflow without --force
  Given interlocks.yml exists WITHOUT interlocks needles
  When I run "interlocks setup --ci=github"
  Then exit 1
  And stderr contains "present, not interlocks-wired" and "--force"
  When I run "interlocks setup --ci=github --force"
  Then exit 0; file overwritten
```

`setup --check` snapshot updates in same PR.

---

## Batch 6 — Skip API

**Precedence (CLI > env > pyproject):**
```gherkin
Scenario: CLI wins
  Given pyproject skip = ["arch"]
  And env INTERLOCKS_SKIP="audit"
  When I run "interlocks check --skip=mutation"
  Then "[mutation] skipped (skip=cli)" in stderr
  And neither "[arch]" nor "[audit]" appear as skipped

Scenario: env wins when no CLI
  Given pyproject skip = ["arch"]
  And env INTERLOCKS_SKIP="audit"
  When I run "interlocks check"
  Then "[audit] skipped (skip=env)" in stderr

Scenario: pyproject when neither
  Given pyproject skip = ["arch"]
  When I run "interlocks check"
  Then "[arch] skipped (skip=pyproject)" in stderr

Scenario: typo exits 2 with suggestion
  When I run "interlocks check --skip=mutaton"
  Then exit 2
  And stderr contains "unknown skip label 'mutaton'" and "Did you mean 'mutation'?"
```

**Crash payload (`tests/test_crash_payload.py`):** `ALLOWLIST_KEYS` contains `"skip"` typed `list[str]` (validated labels only). With `INTERLOCKS_SKIP="secret-token"`, payload contains no `secret-token` substring (env values never leak).

**CI/nightly banner:** non-empty skip registry → first 5 stderr lines match `/skipping: [a-z,\s]+/`.

**Runner contract (`tests/test_runner.py`):** `--skip=mutation` → `_RESULTS` has no `mutation` entry. Non-skipped failing gate + `--skip=mutation` → exit code = failing gate's code (skip never reverses failure).

---

## Onboarding success metric

**Claim:** fresh repo + paste agent prompt → green `interlocks check` in **N=5 commands**.

**Assertion (`tests/e2e/test_agent_onboarding.sh`):** clean tmp dir w/ `pyproject.toml` + one `*.py`. Scripted commands: `pip install interlocks` → `setup --check` (exit 1) → `setup` → `check` → `config`. Pass: total commands ≤ **5**; final `check` exit 0; post-setup `setup --check` re-run (uncounted) reports all rows `installed`; no extra commands required (edits/retries → fail).

---

## Go / No-Go Gates

**Merge (per PR):**
- [ ] New tests above present and asserting listed Givens
- [ ] CI matrix green: 3.11, 3.12, 3.13
- [ ] No `socket`/`urllib`/`http`/`requests`/`httpx`/`sentry`/`posthog` imports added under `interlocks/crash/`
- [ ] Crash-payload allowlist change (Batch 6) co-commits with `tests/test_crash_payload.py` update
- [ ] `interlocks config` snapshot updated for new keys
- [ ] No `interlocks/defaults/` file modified outside Batch 2 scope

**Ship (cumulative, after Batch 6):**
- [ ] `pip install interlocks` succeeds on Python 3.11.0
- [ ] `interlocks config-show ruff` prints bundled config on stock repo
- [ ] Maturity banner: once on fresh clone, never on `CI=true`
- [ ] `setup --ci=github && setup --check` exit 0 with `ci workflow … installed`
- [ ] Skip precedence (CLI>env>pyproject) verified on real workflow run
- [ ] Onboarding E2E: 5-command prompt → green `check`
- [ ] FAQ skim test: 4 JTBDs covered, ≤120 words/entry, all URLs resolve
- [ ] CHANGELOG per batch; 0.2.0 semver bump for Batch 6 (new public API)

**Manual:** banner copy reads neutrally (not apologetic); FAQ scannable in <30s; agents-block v2 renders cleanly when appended to real `CLAUDE.md`.
