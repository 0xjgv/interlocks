<important if="you are editing Python in this repo">

After edits, run `interlocks check`. If a gate fails, fix it and re-run. Do not bypass the pre-commit hook (no `--no-verify`).

| Command | What it does |
|---|---|
| `interlocks check` | First command after edits: fix, format, typecheck, tests, advisory gates |
| `interlocks doctor` | Diagnose paths, tools, config, and setup state when checks fail |
| `interlocks pre-commit` | Pre-commit stage, normally run by the installed git hook |
| `interlocks ci` | PR/CI stage with blocking verification |
| `interlocks nightly` | Scheduled long-running coverage/audit/mutation stage |
| `interlocks warm` | Pre-fetch bundled tool wheels into `~/.cache/uv` for `UV_OFFLINE=1` |
| `interlocks setup --check` | Verify local integrations read-only |
| `interlocks config` | List `[tool.interlocks]` keys, resolved values, and sources |
| `interlocks baseline show` | Print the current quality floor and last advance metadata |
| `interlocks help` | List commands and active thresholds |

Blocking gates fail the command; advisory gates print warnings without masking the main result. Change gate policy in `[tool.interlocks]` only after inspecting `interlocks config` and keeping CLI, hooks, CI, and agents aligned.
</important>
