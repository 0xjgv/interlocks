# interlocks adoption: JTBDs, severity, FAQ draft

## 1. Jobs-to-be-Done

**(a) Opaque defaults.** When I'm evaluating a new quality tool, I want to see exactly which rules will fire on my code before installing, so I can predict the diff and decide whether its taste matches my team's.

**(b) Skipping checks.** When a gate is wrong for my repo right now, I want to silence it without rewriting my pyproject or forking, so I can ship while I fix the underlying issue on my own timeline.

**(c) Agent + automation setup.** When I add interlocks to a repo, I want one command to wire my coding agent, git hooks, and CI to use it, so my team doesn't drift back into ad-hoc checks.

**(d) Python floor.** When I'm choosing quality infrastructure, I want a tool whose Python floor matches the runtime I already support (3.12), so I don't have to bump my project just to run lint.

## 2. Severity ranking (adoption-blocking)

1. **(d) Python 3.13 floor** — hardest gate. `pip install` fails on 3.12; user never reaches the FAQ. Worst because the source only needs 3.12 — the floor is fictional.
2. **(a) Opaque defaults** — soft gate at the trust step. A skeptical engineer won't run it on a real repo without seeing the rule list; "trust me" doesn't survive a senior reviewer.
3. **(c) Setup completeness** — gate at the "make it stick" step. If `setup` silently skips CI, the team falls back to manual runs and abandons within a week.
4. **(b) Per-gate skips** — gate at the "first conflict" step. Day-1 users find tool-native ignores; pain hits later when they want a whole gate off without flipping to advisory.

## 3. FAQ — paste between "Configuration" and "Stages" in README.md

### FAQ

**Q: What styling and type-check rules ship as defaults?**
The bundled ruff config selects 17 rule families (E/F/W/I/UP/B/SIM/RUF/C4/PTH/TCH/ARG/PL/ANN/ERA/PIE/S) with `line-length=99` and `preview=true`; basedpyright runs in standard mode with a small mute list. The full files live at [`interlocks/defaults/ruff.toml`](interlocks/defaults/ruff.toml) and [`interlocks/defaults/pyrightconfig.json`](interlocks/defaults/pyrightconfig.json). **Important:** the moment your project has any `[tool.ruff]` block or a `ruff.toml`/`.ruff.toml` sidecar, the bundled defaults are REPLACED entirely (no merge); same for basedpyright. *Today: read the source. Planned: `interlocks defaults --show ruff` to print resolved config.*

**Q: How do I skip or relax a check?**
No global gate disable today. Options in order of granularity: (1) **Per-rule ignore** in tool-native config — `[tool.ruff.lint] ignore = [...]`, but this replaces the bundled ruff defaults wholesale (see previous Q). (2) **Flip enforcement to advisory** via `[tool.interlocks]` toggles like `enforce_crap=false`, `enforce_mutation=false` — gate still runs, won't fail the build. (3) **`preset = "legacy"`** zeros every threshold and disables enforcement across the suite. (4) **`interlocks check --changed[=<ref>]`** restricts file-level gates to changed `.py` files and skips graph-wide gates. Run `interlocks config` for every key and its resolved value. *Planned: per-gate `--skip=<gate>` and `[tool.interlocks] disabled = [...]`.*

**Q: Does `interlocks setup` wire everything up for me and my agent?**
Mostly. It installs (1) a git `pre-commit` hook running `interlocks pre-commit`, (2) a Claude Code `Stop` hook in `.claude/settings.json` running `interlocks post-edit`, (3) a 13-line block appended to `AGENTS.md` and `CLAUDE.md` teaching agents the seven main commands, and (4) a Claude skill at `.claude/skills/interlocks/SKILL.md`. It does **not** install a GitHub Actions workflow today — wire CI yourself by calling `interlocks ci` from your existing workflow. Verify with `interlocks setup --check` (read-only). *Planned: `interlocks setup --ci=github`.*

**Q: Why does interlocks require Python 3.13? My project is on 3.12.**
The declared floor is conservative. The source uses only 3.12-level syntax (PEP 695 generics in two places; `tomllib` is 3.11+) with no `sys.version_info` guards. The `>=3.13` pin reflects what we currently test against, not a hard syntactic requirement. *Today: pin interlocks in a 3.13 dev-tools venv separate from your project runtime, or open an issue. Planned: drop the floor to 3.12 once a CI matrix exercises every gate on 3.12.*

**Q: Why "interlocks"?**
An interlock is a safety device that blocks an unsafe action until preconditions are met. Each gate — lint, typecheck, test, coverage, mutation, audit, deps, arch — is a literal interlock: it blocks the merge until a specific quality precondition holds.

**Q: How do I run only the gates that touch my changes?**
`interlocks check --changed` runs file-level gates (ruff, basedpyright) only on `.py` files differing from the default branch; `--changed=<ref>` compares against an arbitrary ref. Graph-wide gates (deps, attribution, acceptance) skip entirely under `--changed`. Use it for sub-second feedback during edit-loop work; rely on `interlocks ci` for full-suite enforcement.

**Q: Is interlocks production-ready?**
It's young (v0.1.6, ~2 weeks old) and self-dogfoods every gate against its own codebase in CI. The crash boundary, payload allowlist, and no-background-network invariant are enforced by tests. Reasonable today on side projects and internal tooling; for critical infra, pin a version and watch the CHANGELOG.

## 4. Team suggestions (not raised by user)

- **`interlocks defaults --show <tool>`** — print resolved bundled config inline. Fixes the (a) trust gap.
- **Bundled-vs-overridden status in `interlocks help`** — closes the silent-replacement footgun on ruff/pyright.
- **`--skip=<gate>` + `[tool.interlocks] disabled=[...]`** — global skip closes (b) without wiping bundled defaults.
- **`interlocks setup --ci=github`** — detector exists; only installer is missing.
- **Drop Python floor to 3.12 + CI matrix** — fixes (d) at the source.
- **First-run banner** — one-screen summary of which gates will run and which configs are bundled vs. overridden.
