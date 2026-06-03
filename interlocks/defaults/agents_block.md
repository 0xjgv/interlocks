<important if="you are editing Python in this repo">

After edits, run `interlocks check --json`. Follow `agent.required_actions` before handing work back. If a gate fails, fix it and re-run. Do not bypass the pre-commit hook (no `--no-verify`).

| Command | What it does |
|---|---|
| `interlocks check --json` | First command after edits: fix, format, typecheck, tests, optional acceptance/properties, advisory gates, structured agent actions |
| `interlocks doctor` | Diagnose paths, tools, config, and setup state when checks fail |
| `interlocks hook pre-commit` | Pre-commit stage, normally run by the installed git hook |
| `interlocks ci` | PR/CI stage with blocking verification |
| `interlocks fix unblock` | Multi-rule lint fix: discover + plan + optimize fixable ruff rules into `.lintfix/`; `--apply` mutates after verify, restores on fail |
| `interlocks nightly` | Scheduled long-running coverage/properties/audit/mutation stage |
| `interlocks warm` | Pre-fetch bundled tool wheels into `~/.cache/uv` for `UV_OFFLINE=1` |
| `interlocks setup --check` | Verify local integrations read-only |
| `interlocks config` | List `[tool.interlocks]` keys, resolved values, and sources |
| `interlocks baseline show` | Print the current quality floor and last advance metadata |
| `interlocks help` | List commands and active thresholds |

Blocking gates fail the command; advisory gates print warnings without masking the main result. JSON payloads include `agent.required_actions`, `agent.recommended_actions`, evidence `artifacts`, and policy boundaries. Change gate policy in `[tool.interlocks]` only after inspecting `interlocks config` and keeping CLI, hooks, CI, and agents aligned.
</important>
