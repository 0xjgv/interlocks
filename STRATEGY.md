# interlocks Strategy Memo

## Thesis

- greenfield codebases: adopt interlocks early and enforces high quality code from day one
- brownfield codebases: ratchet existing codebases to high quality
- adoption: bring interlocks to a codebase through a skill, and let model adjust thresholds over time (towards the high quality preset)
- how?

interlocks should be positioned as an opinionated Python quality interlocks for platform and DevEx teams that manage many repositories. Its strongest promise is not “a wrapper around tools”; it is one enforceable quality workflow for linting, typechecking, tests, coverage, dependency hygiene, architecture checks, complexity, and stricter gates when teams are ready.

The AI-era wedge is credible: teams adopting coding agents need hard merge gates because code volume rises faster than review capacity. But the buyer and first serious user is still likely a platform or DevEx owner who already feels CI drift across many Python services.

## Product Story

Lead with the commands that explain the product fastest:

- `interlocks doctor` for adoption diagnostics.
- `interlocks check` for local developer confidence.
- `interlocks ci` for one-line repository verification.
- `interlocks init` for greenfield projects.

Treat mutation testing, CRAP, acceptance tests, and trust scoring as strict or advanced capabilities. They are valuable, but they should not dominate first-run understanding. The default story should be: install or invoke one tool, run one command locally, run one command in CI.

Reduce configuration surface with one preset taxonomy before adding more knobs:

- `baseline` for low-friction adoption.
- `strict` for mature teams that want blocking gates.
- `legacy` for existing repos that need ratcheting instead of instant strictness.
- `agent-safe` only if agent-governance demand becomes clear.

## Near-Term Adoption Loop

Do not expand the feature matrix yet. Package a narrow adoption loop:

1. Start without installation: `uvx --from interlocks il doctor`.
2. `uvx --from interlocks il check` proves local value with the latest release.
3. Shared automation uses pinned or range-pinned specs: `uvx --from 'interlocks>=0.1,<0.2' il ci`, exact `uvx --from interlocks==0.1.5 il ci`, or the GitHub Action `install-command` override.
4. Frequent local users install it permanently with `uv tool install interlocks`; `pipx install interlocks` remains an alternative.
5. A first-class GitHub Action makes adoption copy-pasteable and reports a concise job summary.

Principle: latest for exploration; pinned or range-pinned for repeatability.

PR annotations, PR comments, GitHub Apps, exception workflows, and hosted dashboards should wait until users prove they want the CI workflow in real repositories.

## Hooks Strategy

Hooks should be an adoption accelerator, not the product center. `interlocks ci` remains the source of truth because it is enforceable in shared infrastructure. Hooks exist to shorten feedback loops before code reaches CI.

Keep `interlocks pre-commit` as a first-class command. It should remain hook-manager agnostic so teams can wire it into raw Git hooks, the Python `pre-commit` framework, Lefthook, Husky, Overcommit, or custom monorepo tooling.

`interlocks setup-hooks` should be positioned as convenience, not the only blessed path. Document `interlocks pre-commit` and `interlocks post-edit` as the stable interfaces first; generate hook-manager adapters only after users ask for them.

## Agent Governance Hypothesis

Agent hooks are strategically important, but they should be validated after the core adoption loop works. The commercial wedge to test is: every AI coding agent in an organization should run through the same quality and safety rails before its work is trusted.

Use stable interlocks commands as the common target:

- Post-edit events should run `interlocks post-edit`.
- Agent stop or session end events should run `interlocks check` or a future quick-check mode.
- Pre-tool events could later support policy and security checks.
- Prompt-submit events could later support data-leak or secret-paste guards.

Start with one deterministic agent integration, measure demand, then add adapters for other platforms. Platform-specific roadmaps should be treated as hypotheses because agent hook surfaces are still changing.

## AI-Factory Framing (Hypothesis)

A second, adjacent framing is worth naming so future copy and sub-wedges can test it without distorting the core adoption loop: **interlocks is the machine-verifiable floor for AI-authored Python**. Deterministic, fast, cheap code-quality gates that every agent-produced PR and every LLM-based reviewer trips before merge. Complementary to probabilistic reviewers like CodeRabbit, Greptile, or Diamond, not competing.

Treat this as a sharpening lens for docs and examples, not a rebrand. STRATEGY still anchors on the platform/DevEx buyer until adoption proves otherwise.

Validation signals to watch:

- Three or more of the first ten adopters come from AI-factory contexts (agents authoring most PRs, human review at capacity).
- Inbound mentions Cursor, Claude Code, Copilot, or agent PRs as the trigger.
- Adopters weight `crap`, `mutation`, and `trust` more than `check` and `ci` alone.

Disvalidation signals:

- Adopters remain exclusively generic DevEx/platform teams with no AI-agent context.
- `crap`, `mutation`, and `trust` stay low-traffic vs. `check` and `ci`.

If disvalidated, drop the framing and stay on the current positioning. Do not ship an `agent-safe` preset or agent-specific sub-CLI on the basis of this framing alone.

## Strategic Bets

Focus on three bets until adoption proves a broader roadmap:

1. Adoption doctor plus presets: show what passes, what fails, what config is missing, and the shortest path to green.
2. CI in one line: make the GitHub Action the fastest adoption path, with concise PR-native output before deeper annotation or bot work.
3. Agent governance hooks: validate one integration where deterministic hooks exist and buyer relevance is clear.

Defer hosted dashboards, mutation sophistication, multi-platform hook adapters, PR review bots, and exception workflows until real users ask for them.

## Crash Reporting (Rejected: Default-On Sentry/PostHog)

We considered shipping a third-party error-reporting SDK (Sentry or PostHog) wired in by default and rejected it. The CLI is a quality-gate tool that runs against private repos, on developer laptops and CI runners controlled by other organizations; a default-on SDK that captures locals, `sys.argv`, env vars, or hostnames would leak source-adjacent context to a vendor we do not control, even with allowlist filters that drift over time. It would also make adoption strictly harder — every new buyer with a security review would have to re-justify background network egress that the tool does not need to function. The shipped reporter is an in-process boundary that asks the user whether to report, then opens a pre-filled GitHub Issues URL in the user's browser when accepted. The user reviews and submits the issue through their own GitHub session; non-interactive runs keep the crash payload local only. Design rationale and the allowlisted payload schema live in `SECURITY.md` and `openspec/changes/add-crash-reporter/`.

## OSS vs Business

Launch the CLI as open source. A local developer quality tool needs trust, easy installation, and low-friction experimentation. `uvx` should let teams try the latest release immediately before deciding whether to install it permanently; shared automation should pin or range-pin the package spec. OSS is the adoption wedge and credibility layer.

Do not treat the CLI alone as the business. The commercial product should be the control plane around it: organization policies, GitHub integration, compliance reporting, exception workflows, repo health trends, and visibility into AI-generated-code risk.

The clean model is:

- OSS core: local CLI, CI command, presets, diagnostics, and repo-level gates.
- Paid layer: org-wide policy management, hosted reporting, PR annotations at scale, exception approvals, and compliance evidence.

## YC-Style Advice

A YC partner would likely push for focus and user contact over more features. The right question is not “OSS or SaaS?” first. It is: who has urgent pain today, and will they adopt this in real repositories this week?

The sharpest wedges to test are:

- DevEx teams can standardize Python CI across many repos in one afternoon.
- Teams using AI coding agents need hard quality gates before code merges.
- Python platform teams need one enforceable policy layer over Ruff, pytest, coverage, and typecheck.

Get 10 real users, ideally platform engineers responsible for multiple Python repos. Watch them install it, run it, fail on it, and decide whether they would keep it. Their objections should drive the next simplification.

If 10 teams do not care about the adoption loop, a dashboard will not save it. If they do care, the business path becomes obvious: central policy and fleet visibility.
