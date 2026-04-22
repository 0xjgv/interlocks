# CLAUDE

## Install

- `pipx install pyharness` (or `uv tool install pyharness` for uv users). All tools ship with the CLI.

## Commands

- After edits: `harness check` — fix, format, typecheck, test, suppression report
- Pre-commit: `harness pre-commit` — staged files only (auto via git hook)
- CI: `harness ci` — read-only lint, format check, typecheck, dep audit, complexity gate (lizard, CCN 15), tests with coverage
- Audit: `harness audit` — audit dependencies for known vulnerabilities (via pip-audit)
- Coverage: `harness coverage --min=0` — coverage.py with threshold + uncovered listing
- CRAP (advisory): `harness crap --max=30` — complexity × coverage gate
- Mutation (advisory): `harness mutation --min-coverage=70 --max-runtime=600` — mutmut
- Setup: `harness setup-hooks` to install git pre-commit hook
- Auto-format: runs automatically after Claude edits via `Stop` hook (post-edit)
