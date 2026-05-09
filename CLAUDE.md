# interlocks

Zero-config Python quality CLI: lint, format, typecheck, test, coverage, acceptance, audit, deps, arch, CRAP, mutation. Self-dogfooded.

Python 3.11+, uv-managed. From 0.2.0 the wheel ships zero runtime deps; gates are dispatched through `uvx` / `uv run --with` at versions pinned in `interlocks/defaults/tools.py`. Tools: ruff, basedpyright, coverage.py, pytest + pytest-bdd, interlocks-mutmut, deptry, import-linter, pip-audit, lizard.

## Project map

- `interlocks/cli.py` — entrypoint (also `il`/`ils`/`ilock`/`ilocks`)
- `interlocks/stages/` — composite stages (`check`, `ci`, `nightly`, `pre-commit`)
- `interlocks/tasks/` — single-purpose gates (one per subcommand)
- `interlocks/defaults/` — bundled tool configs (ruff, pyright, coverage, importlinter)
- `interlocks/config.py` — threshold resolver (CLI flag > `[tool.interlocks]` > bundled default)
- `tests/features/` + `tests/step_defs/` — pytest-bdd acceptance over public CLI
- `README.md` — user-facing overview
- `STRATEGY.md` — product positioning + roadmap
- `AGENTS.md` — agent-specific guidance
- `PYPI_RELEASE_CHECKLIST.md` — release procedure

<important>
You own this product and the codebase.
</important>

<important if="you need to run quality gates, tests, or inspect config">

| Command | What it does |
|---|---|
| `interlocks check` | Run after edits |
| `interlocks pre-commit` | Pre-commit stage (auto via hook) |
| `interlocks ci` | PR/CI stage |
| `interlocks nightly` | Nightly cron stage |
| `interlocks warm` | Pre-fetch bundled tool wheels into `~/.cache/uv` for `UV_OFFLINE=1` |
| `interlocks setup` | Install local hooks, agent docs, Claude skill |
| `interlocks setup --check` | Verify local integrations read-only |
| `interlocks setup --ci=github` | Install GitHub Actions workflow when absent |
| `interlocks setup --ci=github --check` | Verify GitHub CI wiring read-only |
| `interlocks help` | List subcommands + thresholds |
| `interlocks config` | List config keys + resolved values |
</important>

<important if="you are adding a new gate or subcommand">
- Add task under `interlocks/tasks/`
- Register in the relevant stage composition under `interlocks/stages/`
- Cover with a Gherkin scenario in `tests/features/interlock_cli.feature`
</important>

<important if="you are reading thresholds or tool defaults in code">
- Resolve through `interlocks/config.py` — never read defaults inline, or CLI flags + `[tool.interlocks]` overrides will be bypassed
</important>

<important if="you are documenting or changing configuration">
- All overrides live under `[tool.interlocks]` in `pyproject.toml` — run `interlocks config` for the full key list, do not duplicate defaults in docs
- Precedence: CLI flag > `[tool.interlocks]` > bundled defaults in `interlocks/defaults/`
- Project's own `[tool.<tool>]` or sidecar (`ruff.toml`, `.coveragerc`, `pyrightconfig.json`, `.importlinter`) replaces the bundled default for that tool
- Per-tool version pins resolve through `[tool.interlocks.tools]` (e.g. `ruff = "0.14.0"`) > `interlocks/defaults/tools.py::DEFAULTS`. Read pins via `cfg.tool_version(name)`; never hardcode a version string at a call site
</important>

<important if="you are touching crash handling or the boundary in interlocks/cli.py">
- `interlocks/cli.py::main` is the SINGLE crash boundary — wraps task dispatch in `CrashBoundary`. Do not install `sys.excepthook`, do not wrap `try/except Exception` around full-task dispatch, do not add a second boundary anywhere
- `interlocks/crash/transport.py` is the only place that renders a payload to a URL. Do NOT add `socket`, `urllib.request`, `http.client`, `requests`, `httpx`, `sentry_sdk`, or `posthog` to any file under `interlocks/crash/`; `tests/test_crash_transport.py` enforces the no-background-network boundary via source introspection
- Capture path failures must NEVER mask the original exception (invariant I6). Reporter errors print one `(crash reporter failed: ...)` line to stderr; the original exception still re-raises and produces the canonical Python traceback
- Payload fields are an allowlist defined in `interlocks/crash/payload.py`. Never widen it without updating `SECURITY.md` and the negative test in `tests/test_crash_payload.py`
</important>
