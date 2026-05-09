<important if="you need to run quality gates, tests, inspect config, or diagnose failures">

`interlocks setup` installs local feedback loops: git pre-commit hook, Claude Code Stop hook, agent docs, and the bundled Claude skill. CI still needs explicit project wiring; use `interlocks setup --ci=github` when available, or add CI manually.

| Command | What it does |
|---|---|
| `interlocks check` | First command after edits: fix, format, typecheck, tests, advisory gates |
| `interlocks doctor` | Diagnose paths, tools, config, and setup state when checks fail |
| `interlocks pre-commit` | Pre-commit stage, normally run by the installed git hook |
| `interlocks ci` | PR/CI stage with blocking verification |
| `interlocks nightly` | Scheduled long-running coverage/audit/mutation stage |
| `interlocks warm` | Pre-fetch bundled tool wheels into `~/.cache/uv` for `UV_OFFLINE=1` |
| `interlocks setup` | Install local hooks, agent docs, and Claude skill |
| `interlocks setup --check` | Verify local integrations read-only |
| `interlocks config` | List `[tool.interlocks]` keys, resolved values, and sources |
| `interlocks help` | List commands and active thresholds |

Blocking gates fail the command; advisory gates print warnings without masking the main result. Change gate policy in `[tool.interlocks]` only after inspecting `interlocks config` and keeping CLI, hooks, CI, and agents aligned.
</important>
