# Onboarding Flow Design — interlocks v0.1.6

**Lens:** what the human/agent experiences moment-to-moment from `pip install` to first useful output.

---

## 1. First-60-Seconds Map

| t (s) | Person sees | Friction |
|---|---|---|
| 0–10 | `pip install interlocks` resolver text | OK |
| 10 | Empty terminal | **No post-install hint.** ruff (`ruff check .`), biome (`biome init`), pre-commit (`pre-commit install`) all print one. interlocks does not. |
| 10–30 | Reads README or guesses `--help` | **High load.** `help` lists 25 commands flat; `setup`/`check`/`config` not visually elevated. |
| 30 | Runs `interlocks setup` | OK once they find it |
| 30–45 | 4 status rows + "Next Steps" | **Silent gap:** no GH Actions row. Agent cannot tell CI is unconfigured. |
| 45–60 | Runs `interlocks check` | First useful signal arrives here |

**Gold-standard delta.** ruff/biome/pre-commit each print one shell-line saying "what was wired, what to run next." interlocks' setup buries the ask: "Next Steps" lists `doctor` first (diagnose) before `check` (produce value) — wrong primary CTA for a first-timer.

**Peak load moment:** t=10s, post-install void. **Fix:** first-run banner when any subcommand runs with no prior setup (see §5).

---

## 2. Drop-In Agent Prompt

```
You are onboarding `interlocks` (Python quality CLI) to this repo.

Step 1 — Detect repo shape:
  - No `pyproject.toml` at repo root → STOP. Tell user "interlocks needs
    a pyproject.toml. Run `uv init` then re-run." Do not proceed.
  - No `[project]`/`[tool.poetry]` table AND no `*.py` under repo root
    → STOP. "Not a Python repo."

Step 2 — Detect prior install:
  Run `interlocks setup --check`. Exit 0 → skip to Step 4. Exit 1 →
  continue.

Step 3 — Install:
  - `pip install interlocks` (or `uv add --dev interlocks` if uv.lock,
    or `poetry add --group dev interlocks` if poetry.lock).
  - `interlocks setup`. Confirm every "Status" row says "installed".

Step 4 — Verify and produce first signal:
  - `interlocks check`. Report exit code + failing gate names (`✗` lines).
  - `interlocks config`. Show user `coverage_min`, `crap_max`, `preset`.

Step 5 — Report:
  - One paragraph: what installed, what passed, what failed, active
    thresholds.
  - For failed gates, propose fixes per agents-block. NEVER lower a
    threshold without asking.

Constraints: never run `git commit --no-verify`; never edit
`[tool.interlocks]` thresholds without explicit approval. If `interlocks`
not on PATH, fall back to `python -m interlocks.cli`.
```

---

## 3. Agents-Block v2 (≤30 lines)

Current 13-line block lists commands but answers none of: *which gates block? how do I skip one? where does config live?* Agent reads it, still guesses.

```markdown
<important if="you are working in this interlocks repo">

## interlocks quick reference

| Command | When | Blocks commit? |
|---|---|---|
| `interlocks check` | After edits | yes (lint/format/type/test) |
| `interlocks pre-commit` | Auto via git hook | yes |
| `interlocks ci` | Pre-PR / CI parity | yes + advisory CRAP/mutation |
| `interlocks nightly` | Long-running gates | n/a (cron) |
| `interlocks config` | Inspect thresholds | n/a |
| `interlocks setup --check` | Verify install | n/a |

**Blocking vs advisory:** `lint format typecheck test coverage audit
deps arch` block. `crap mutation behavior-attribution` are advisory by
default (red ✗ ≠ exit 1 — read the exit code). Flip with
`enforce_crap=true`, `enforce_mutation=true` in `[tool.interlocks]`.

**Tuning:** all overrides in `[tool.interlocks]` (pyproject.toml).
Precedence: CLI flag > `[tool.interlocks]` > preset > bundled default.
Inspect with `interlocks config`. Never edit defaults inline.

**Per-rule ignores** live in tool-native config (`[tool.ruff.lint]
per-file-ignores`, `[tool.basedpyright] reportX=false`). Adding any
tool-native config replaces the bundled default wholesale.

**Escalation — ask user first:** lowering a threshold, switching preset,
`--no-verify`, disabling enforcement.
</important>
```

26 lines. Adds the three things v1 missed: blocking matrix, override precedence, escalation list.

---

## 4. CI Installer — `interlocks setup --ci`

**Trigger:** user runs `interlocks setup --ci` (or interactive `setup` prompts after detecting `.github/` but no workflow).

**Person sees:**

```
Setup CI
  detected: .github/workflows/ exists, no interlocks workflow
  will write: .github/workflows/interlocks.yml (uses ./action.yml@v0.1)
  will not modify: existing workflows
Continue? [Y/n]
```

**On accept:** writes a 12-line workflow calling the bundled composite action. Idempotency: detector at `setup_state.py:121` already greps `_CI_WORKFLOW_NEEDLES`; if present, prints `✓ already wired (path: …)` and exits 0.

**Decision points:**

| Step | Decision | Default |
|---|---|---|
| Detect `.github/` | — | auto |
| Confirm overwrite | y/n | n if file exists |
| Pin action version | semver / main | `@v0.1` (tracks minor) |

**Recovery:** if write fails (perms), prints YAML to stdout with "paste this to .github/workflows/interlocks.yml". Never silent-fails.

**Status row added** to `setup --check`: `ci workflow | .github/workflows/interlocks.yml | installed/missing`. Closes the §1 silent gap.

---

## 5. Maturity Banner — Honest One-Liner

First time `interlocks <anything>` runs in a project (no `.interlocks/` cache):

```
interlocks 0.1.6 — early release. Defaults are opinionated; run
`interlocks config --explain` to see active rules.
Issues: github.com/.../interlocks/issues
```

**Why this works:** acknowledges age (`0.1.x`, "early"), points at opacity via a new `--explain` flag (dumps bundled `ruff.toml` select/ignore + pyright flags — closes the Q1 visibility gap), gives an out (issue tracker). Sets expectation without apologizing. Suppress on subsequent runs via `.interlocks/.seen`.

**Avoid:** "beta", "experimental", "use at your own risk" — scare without informing. **Avoid:** silent confidence — users meet opacity at the worst moment (a failing gate they cannot explain).
