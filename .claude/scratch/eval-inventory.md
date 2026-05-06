# Inventory: shipped vs `change-plan.md`

Working-tree only — nothing committed since `84d8464`. 60 dirty + 2 new (`skip.py`, `defaults/github_workflow.yml`).

## B1 — README FAQ

| Item | Status | Evidence |
|---|---|---|
| `## FAQ` block at `README.md:235-259` | DONE | 6 entries shipped vs 8 planned. ~20 lines vs ~110 planned. |
| Q1 styling | DONE | 237-239 — names `config show`. |
| Q2 extends? | DONE | 241-243 — replace not extend. |
| Q3 ignore/skip | DONE | 245-247 — CLI/env/pyproject. |
| Q4 setup vs CI | DONE | 249-251 — references `setup --ci=github`. |
| Q5 Python versions | DONE | 253-255 — 3.11/3.12/3.13. |
| Q6 production-ready | DONE | 257-259. |
| Other 2 planned entries | MISSING | Only 6 of 8 shipped. |

## B2 — Python 3.11 floor

| Item | Status | Evidence |
|---|---|---|
| `requires-python=">=3.11"` | DONE | `pyproject.toml:6` |
| Classifiers | DONE | `pyproject.toml:12,14` (3.11 + 3.13; 3.12 absent) |
| `[tool.basedpyright] pythonVersion="3.11"` | DONE | `pyproject.toml:185` |
| PEP 695 → TypeVar at `hook_setup.py:14` | DONE | `hook_setup.py:9,14` `_Container = TypeVar(...)` |
| PEP 695 → TypeVar at `config.py:684` | DONE | `config.py:711` `_PathFallback = TypeVar(...)` |
| `defaults/ruff.toml` `target-version="py311"` | DONE | line 8 |
| `defaults/pyrightconfig.json` `pythonVersion="3.11"` | **MISSING** | file unchanged; no `pythonVersion` key |
| `defaults/scaffold_pyproject.toml` `>=3.11` | DONE | line 4 |
| `.github/workflows/ci.yml` matrix `["3.11","3.12","3.13"]` | DONE | line 15 |
| 3.13 audit AGENTS/README/CLAUDE | DONE | `AGENTS.md:26` "3.11+", `README.md:255`, `CLAUDE.md:5` |
| `action.yml` default 3.13→3.11 | DONE (bonus) | `action.yml:8` — not in plan |

## B3 — `interlocks config show <tool>`

| Item | Status | Evidence |
|---|---|---|
| `tasks/config_show.py` new module | PARTIAL | logic INLINED at `tasks/config.py:60-184` (`_cmd_config_show`); single CLI verb `config show <tool>` instead of separate `config-show`. |
| `defaults_path.provenance_probe` | PARTIAL | renamed: `project_config_source` + `tool_config_source` + `ToolConfigSource` dataclass (`defaults_path.py:28-88`); `config_flag_if_absent` refactored to call it (91-115). |
| `cli.py` registers `config-show` | MISSING-by-design | dispatched within `cmd_config` (`tasks/config.py:60-62`). |
| "Next steps" pointer to `config show` | MISSING | `_print_next_steps` (290-298) lists init/presets/help; no mention. |
| `--bundled-only`, `--json` | DONE | `tasks/config.py:111-114,176-184` |
| Whitelist ruff/basedpyright/coverage/import-linter | DONE | `_TOOL_SPECS` (42-54) |
| `tests/test_defaults_path.py` provenance × 4 | PARTIAL | +45 lines per `--stat`; scenario count not audited |
| `tests/tasks/test_config_show.py` new | MISSING | file absent |
| Gherkin scenario | MISSING | no `config-show` / `config show` scenarios in `tests/features/` |

## B4 — Setup ergonomics + agents v2 + maturity banner

| Item | Status | Evidence |
|---|---|---|
| Next-steps reorder (`check` first, `doctor` second) | DONE | `tasks/setup.py:77-82` (+ bonus `setup --ci=github` line) |
| agents-block v2 | PARTIAL | `defaults/agents_block.md` 13→**18** lines (plan: 26). Adds intro + blocking/advisory footer; missing override-precedence + escalation list. |
| `AGENTS.md` mirror v2 | PARTIAL | 44 lines, says "3.11+" but does not mirror v2 escalation rules |
| `_maybe_print_maturity_banner` in `cli.py::main` | **MISSING** | grep `maturity\|.seen\|preview\|alpha` — no hits |
| `.seen` marker | **MISSING** | no `.interlocks/.seen` references anywhere |

## B5 — `setup --ci=github` writer

| Item | Status | Evidence |
|---|---|---|
| Bundled workflow | DONE | `defaults/github_workflow.yml` 14 lines, `uses: 0xjgv/interlocks@v1` (plan suggested `@v0.1`) |
| `setup_state.SETUP_ARTIFACTS` row | PARTIAL | separate `CI_ARTIFACTS` tuple + `ci_artifact_statuses` (`setup_state.py:160-182`) — not merged. Different design. |
| `ci_setup.py` new module | MISSING-by-design | inlined at `tasks/setup.py:85-107` (`_cmd_setup_ci_install`) |
| `--ci=github` parsing | DONE | `tasks/setup.py:52-65` (`_parse_args`) |
| `--ci=github --check` | DONE | `tasks/setup.py:35-36,110-120` |
| Conflict handling | PARTIAL | `fail_skip` when file exists w/o needles (90-94); NO `--force` flag |
| `action.yml` updates | DONE | line 8 (also counts under B2) |
| `tests/stages/test_setup_hooks*` | UNKNOWN | `test_setup_hooks_integration.py` modified per stat |
| Gherkin scenario | MISSING | no `--ci` scenarios |

## B6 — Skip API

| Item | Status | Evidence |
|---|---|---|
| `interlocks/skip.py` | DONE | 134 lines; `SkipPolicy` (frozen dataclass) instead of `SkipRegistry` |
| Validation set | PARTIAL | validates against `config.SKIP_LABELS` (`config.py:39-54`, 14 gate labels) — STAGE labels (`check`/`ci`/`nightly`/`pre-commit`) NOT permitted. Plan §B6 prescribed `TASKS.keys() ∪ STAGE_LABELS`. |
| `[tool.interlocks] skip` schema | DONE | `config.py:485` field, 648 parse, 802-810 strict validation, 294-296 `ConfigKeyDoc` |
| CLI `--skip=` | DONE | `skip.py:103-109`; `cli.py:392` `validate_cli_skip()` between `preflight` and `CrashBoundary` |
| `INTERLOCKS_SKIP` env | DONE | `skip.py:20,36-38` |
| Precedence CLI>env>project | DONE | `skip.py:32-41` |
| `runner.run/run_tasks` filter + warn | DONE | `runner.py:212-215,232-236` |
| 4 stages: filter + banner | DONE | check.py:25-29,74-75; ci.py:16-20,41-43,70-78; nightly.py:9,19-27; pre_commit.py:11,31-32 |
| `crash/payload.py` allowlist `+ "skip"` | **MISSING** | payload.py unchanged in `--stat`; no `skip` reference |
| `test_crash_payload.py` allowlist + negative test | **MISSING** | `ALLOWLIST_KEYS` (line 29-42) still 12 keys |
| `tests/test_skip.py` new | MISSING | absent (coverage in `test_cli.py:340-349,379` + `test_config.py:140-182`) |
| Gherkin scenarios `--skip`, env typo→exit2 | MISSING | none |
| `tasks/config.py` surfaces resolved `skip` | DONE | line 226 renderer |
| README FAQ entry "active-tense" | DONE | `README.md:247` describes shipped behavior |
| CHANGELOG / 0.2.0 bump | **MISSING** | `pyproject.toml:3` still `0.1.6`; `CHANGELOG.md:8-13` `[Unreleased]` only typecheck fix |

## Headline

**~38 of 50 items DONE; ~7 PARTIAL; ~12 MISSING.** All 6 batches present in working tree, uncommitted. Critical-path B2/B3/B6 functional end-to-end. Biggest gaps: (1) `crash/payload.py` allowlist + negative test for `skip` — plan §B6 mandated both; neither shipped (architecturally defensible — skip never enters payload); (2) maturity banner + `.seen` from B4 entirely absent; (3) Gherkin scenarios for `config show`, `setup --ci=github`, `--skip` — none added; coverage relies on `test_cli.py`/`test_config.py` units only; (4) `defaults/pyrightconfig.json` not updated to `pythonVersion="3.11"` (project's own pyproject has it; bundled default does not); (5) skip-validation rejects stage labels (only 14 gate labels permitted), contradicting plan §B6 which prescribed `TASKS.keys() ∪ STAGE_LABELS`; (6) no CHANGELOG entries or version bump for any of B2/B3/B5/B6.
