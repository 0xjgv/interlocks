# CLAUDE

## Commands

- After edits: `uv run harness check` — fix, format, typecheck, test, suppression report
- Pre-commit: `uv run harness pre-commit` — staged files only (auto via git hook)
- CI: `uv run harness ci` — read-only lint, format check, typecheck, dep audit, complexity gate (lizard, CCN 15), tests with coverage
- Audit: `uv run harness audit` — audit dependencies for known vulnerabilities (via pip-audit)
- Coverage: `uv run harness coverage --min=0` — coverage.py with threshold + uncovered listing
- CRAP (advisory): `uv run harness crap --max=30` — complexity × coverage gate
- Setup: `uv run harness setup-hooks` to install git pre-commit hook
- Auto-format: runs automatically after Claude edits via `Stop` hook (post-edit)
