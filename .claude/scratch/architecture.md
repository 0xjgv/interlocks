# Architecture Perspective: Python compat + config visibility + skip API

## System Context

Three surfaces touch one boundary: bundled defaults (`interlocks/defaults/`), project config (`pyproject.toml [tool.interlocks]` + tool sidecars), per-invocation CLI. `config.py` is the resolver; `defaults_path.config_flag_if_absent` is the bundled-vs-project switch; `runner.run_tasks` is the execution funnel. All changes modify or extend those three.

## Component Map

### Existing (Modified)
| Component | Location | Change |
|---|---|---|
| Pyproject metadata | `pyproject.toml:6` | `requires-python>=3.11`; align `target-version`/`pythonVersion` |
| PEP 695 generic | `hook_setup.py:14` | rewrite as `TypeVar` + `Generic` |
| PEP 695 generic | `config.py:684` | rewrite with `TypeVar` |
| Config resolver | `config.py:_load_config_cached` | parse `skip: list[str]`; surface in `value_sources` |
| CLI dispatcher | `cli.py::main` | parse `--skip=`, read `INTERLOCKS_SKIP`; build process-scoped `SkipRegistry` |
| Runner | `runner.py::run`, `run_tasks` | consult `SkipRegistry.contains(label)` before submit; emit `[label] skipped (skip=<src>)` row |
| Stages | `stages/{check,ci,nightly,pre_commit}.py` | filter task list through `SkipRegistry`; never silent |
| Config reporter | `tasks/config.py::cmd_config` | add `Bundled tool configs` summary row |

### New
| Component | Location | Responsibility | Depends On |
|---|---|---|---|
| `cmd_config_show` | `tasks/config_show.py` | render resolved tool config + provenance | `defaults_path.path`, `_load_pyproject`, `tomllib`, `json` |
| `SkipRegistry` | `skip.py` | freeze skipped labels per CLI run; record source | `InterlockConfig`, `os.environ`, `sys.argv` |
| `provenance_probe` | `defaults_path.py` (extend) | return `(path, source)` per tool | `has_project_config` |

### Unchanged but Affected
| Component | Why |
|---|---|
| `tasks/_ruff.py`, `tasks/typecheck.py` | consume `provenance_probe` for `config show`; runtime args identical |
| `setup-hooks` | post-PEP-695 rewrite must keep hook script byte-identical |
| `crash/payload.py` | adding `skip` to invocation context requires payload-allowlist update + negative test |

## Interface Specifications

### `interlocks config show [<tool>] [--json]`
- **Direction**: CLI → `cmd_config_show` → stdout
- **Input**: optional `tool ∈ {ruff, pyright, coverage, importlinter}` (absent ⇒ all four); `--json` flag.
- **Output (text)**: `[tool] (<source>)` header + resolved body — TOML for ruff/coverage/importlinter, JSON for pyright. `<source>` ∈ `bundled` | `project: pyproject.toml [tool.X]` | `project: <sidecar>`.
- **Output (json)**: `{"tool", "source", "path", "config"}`; array when no tool.
- **Errors**: unknown tool → exit 2; unreadable bundled file → exit 1.
- **Guarantees**: read-only; idempotent; never copies bundled file into project (use `interlocks init`); preflight-exempt.

### Skip API: `--skip` ⊕ `[tool.interlocks] skip` ⊕ `INTERLOCKS_SKIP`
- **Direction**: CLI ⊕ env ⊕ pyproject → `SkipRegistry` → `runner` + stages
- **Input**: comma-separated labels matching `Task.label` or stage name. Unknown → exit 2 with suggestion.
- **Output**: yellow `[label] skipped (skip=<source>)` via `warn_skip`; task not submitted.
- **Guarantees**: skip set frozen before first Task executes; skipped labels never appear in `_RESULTS` as `(label, True)`; exit code unaffected.
- **Precedence**: CLI > `INTERLOCKS_SKIP` > `[tool.interlocks] skip`.

### TOML schema additions
```toml
[tool.interlocks]
skip = ["mutation", "arch"]   # list[str]; validated against task/stage names at load
```

## Failure Modes

| Failure | Components | Impact | Recovery |
|---|---|---|---|
| Typo'd skip (`--skip=lin`) | `SkipRegistry` | silent no-op; user thinks gate skipped | validate vs `TASKS.keys() ∪ stage labels`; exit 2 + suggestion |
| `INTERLOCKS_SKIP` in CI but not pre-commit | `stages/pre_commit` | divergent enforcement | hook `exec`s with env (already); document |
| 3.11 floor; user on 3.10 | install boundary | install-time fail | `requires-python>=3.11` enforces |
| `config show --json` on broken `pyproject.toml` | `tomllib` | mid-render crash | catch `TOMLDecodeError` → `{"error":"<msg>"}`; exit 1 |
| Skip masks `audit`/`mutation` in CI | `stages/ci` | hides vulnerability/mutation gate | banner whenever skip is non-empty in `ci`/`nightly` |

## Invariants

- `[tool.interlocks]` remains the single authoritative override surface — `interlocks config` lists every key.
- Skip NEVER reverses a failing exit code already accumulated by a non-skipped gate in the same stage.
- Bundled `defaults/` files are read-only at runtime; merged/derived configs land in `~/.cache/interlocks/`.
- Single crash-boundary contract (cli.py) untouched; new paths sit inside the boundary.
- `find_project_root` + `@cache` keyed on resolved path semantics unchanged.

## Coupling

- **New deps**: one module (`skip.py`); stdlib-only. No third-party.
- **Strained**: `runner.py` had no label filtering — `SkipRegistry` read once per `run_tasks` keeps runner pure.
- **Decoupling**: extend `defaults_path.config_flag_if_absent` with a `provenance` return rather than scattering `has_project_config` calls; one API for decide + render-source.

## Integration Points

- **GitHub Actions** (`action.yml`) — `INTERLOCKS_SKIP` propagates automatically.
- **Pre-commit hook** — `exec`s user interpreter, inherits env; CLI-flag path needs hook edit (acceptable).
- **`interlocks setup`** — MUST NOT install a `skip = [...]` block; user-authored only.

## Decisions

**(1) Python floor `>=3.11`.** Rewrite two PEP 695 generics with `TypeVar`/`Generic` (~10 LOC, 30 min, low risk). Can't drop to 3.10 without backporting `tomllib` (3 files) to `tomli` — not worth it. Matches pip-audit's floor; covers ~95% of active users. CI matrix: 3.11/3.12/3.13. Update `defaults/ruff.toml target-version` and bundled `pyrightconfig.json pythonVersion` to `py311`.

**(2) `extend_defaults` rejected as flag, accepted as command.** Silent merge produces irreproducible config. Instead `interlocks config show ruff --bundled-only` lets users copy the starter into their `[tool.ruff.lint]` and own it explicitly. Single source of truth per project.

**(3) Skip API: all three surfaces, strict validation.** CLI > env > pyproject; unknown labels exit 2. Mirrors pre-commit's `SKIP=` env (so `INTERLOCKS_SKIP=mutation interlocks ci` reads naturally), mypy's `disable_error_code` for pyproject, ruff's `--ignore` style for CLI. Composition keeps each surface honest: CLI ad-hoc, env CI overlay, pyproject permanent policy. `ci`/`nightly` print a banner when skip is non-empty so masked gates are visible in CI logs.
