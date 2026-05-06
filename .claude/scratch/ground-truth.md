# Ground-truth: interlocks installer experience (v0.1.6)

## Q1 — Default styling rules

- **File**: `defaults/ruff.toml:1-43` — `target-version="py313"`, `line-length=99`, `preview=true`, `select` of 17 families (E/F/W/I/UP/B/SIM/RUF/C4/PTH/TCH/ARG/PL/ANN/ERA/PIE/S), `ignore` of 9 codes. Pyright muted-options at `defaults/pyrightconfig.json:1-9`; coverage at `defaults/coveragerc:1-10`. (HIGH)
- **Replace, not extend**: `tasks/_ruff.py:9-22` → `defaults_path.py:39-66` (`config_flag_if_absent`) returns `[]` the moment the project owns `[tool.ruff]` OR a `ruff.toml`/`.ruff.toml` sidecar — bundled drops out entirely. Same for typecheck (`tasks/typecheck.py:11-19`, `[tool.basedpyright]` / `pyrightconfig.{json,toml}`). No merge. (HIGH)
- **Visibility**: `interlocks help` (`cli.py:233-273`) and `interlocks config` (`tasks/config.py:28-54`) print `[tool.interlocks]` keys with sources, but NEITHER renders bundled ruff `select`/`ignore` or pyright flags. Bundled `ruff.toml` ships as package data (`pyproject.toml:51`), resolved via `defaults_path.path()`; no CLI surfaces the path. (HIGH)

## Q2 — Skipping checks

- **No global gate disable**, no `--skip=<gate>`, no `[tool.interlocks] disabled=[...]`. Confirmed by grep across `cli.py`, `stages/`, `runner.py`, `config.py`. (HIGH)
- **Per-task knobs flip blocking↔advisory, not on/off**: `enforce_crap` (`config.py:208`), `enforce_mutation` (223), `enforce_behavior_attribution` (209, auto-on for interlocks), `run_mutation_in_ci` / `mutation_ci_mode` (217-256), `run_acceptance_in_check` (230), `require_acceptance` (282). Gate still runs; exit code changes. (HIGH)
- **Per-rule ignores live in tool-native config** (`[tool.ruff.lint] ignore`, `per-file-ignores`, `[tool.basedpyright] report*=false`). Adding any of those replaces the bundled default wholesale (Q1). (HIGH)
- **Scope shrink**: `check --changed[=<ref>]` (`stages/check.py:50`, `runner.py:140-152`) restricts file-level gates to changed `.py`; graph-wide gates (deps, attribution, acceptance) + tests skip via `_skip_under_changed` (`check.py:114-123`). `pre-commit` no-ops on empty staged `.py` (`pre_commit.py:21`). (HIGH)
- **Coarse switch**: `preset="legacy"` (`config.py:78-93`) zeros thresholds + disables enforcement. (HIGH)

## Q3 — `interlocks setup`

`tasks/setup.py:21-56` → three installers:

- **Git pre-commit hook** (`hook_setup.py:52-62`): writes `.git/hooks/pre-commit` calling `<python> -m interlocks.cli pre-commit`, chmod 0o755. Overwrites unconditionally. (HIGH)
- **Claude Stop hook** (`hook_setup.py:63-73`,`37-49`): merges into `.claude/settings.json` a `Stop` hook running `interlocks.cli post-edit`; dedupes prior entries. (HIGH)
- **Agent docs** (`tasks/agents.py:23-41`): for `AGENTS.md` AND `CLAUDE.md` (`setup_state.py:29`), creates if missing, else APPENDS the bundled block when the file doesn't already mention `interlocks check`/`il check` (`setup_state.py:129,145-148`). Block = `defaults/agents_block.md` — 13 lines, one `<important if=...>` table mapping 7 commands (check/pre-commit/ci/nightly/setup/setup --check/help/config) to one-liners. Never edits in place. Idempotent only via substring guard. (HIGH)
- **Claude skill** (`tasks/setup_skill.py:23-35`): byte-copies `defaults/skill/SKILL.md` (111 lines: frontmatter, trigger heuristics, workflow router, recovery patterns) to `.claude/skills/interlocks/SKILL.md`. (HIGH)
- **`setup --check`** (`tasks/setup.py:59-69`): static detectors only (`setup_state.py:160-172`); exit 1 if any artifact stale. (HIGH)
- **NOT installed**: GitHub Actions workflow (detector at `setup_state.py:121-126` is read-only; no installer). No `[tool.interlocks]` block written. (HIGH)

## Q4 — Is the `>=3.13` floor real?

- **Declared**: `pyproject.toml:6`; `defaults/ruff.toml:8`, `[tool.basedpyright] pythonVersion="3.13"`. (HIGH)
- **3.13-only syntax**: NONE. Grep across `interlocks/**/*.py` for `assert_type`, `TypeIs`, `ReadOnly`, top-level `type X=` PEP 695 alias statements, `@override`, `Self` — zero hits. (HIGH)
- **3.12+ syntax (PEP 695 generics)**: exactly two — `hook_setup.py:14` `def _reset_invalid_container[T: (...)]`, `config.py:684` `def _resolved_path[T]`. Both compile on 3.12. (HIGH)
- **`tomllib`** (`config.py:11`, `tasks/audit.py:7`, `tasks/doctor.py:13`) — stdlib since 3.11. No constraint. (HIGH)
- **No `sys.version_info` guard** anywhere in `interlocks/`. (HIGH)
- **Inference**: nothing observable in source forces ≥3.13; PEP 695 generics force ≥3.12. (HIGH on syntax; MEDIUM on "arbitrary" — possible 3.13 stdlib-semantic dependencies not surfaced by grep.)

## Confidence
Confirmed: 19. Probable: 1.
