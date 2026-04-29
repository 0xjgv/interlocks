# interlocks

Zero-config Python quality CLI: lint, format, typecheck, test, coverage, acceptance, audit, deps, arch, CRAP, mutation. Self-dogfooded.

Python 3.13, uv-managed. Tools: ruff, basedpyright, coverage.py, pytest + pytest-bdd, interlock-mutmut, deptry, import-linter, pip-audit, lizard.

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
</important>
