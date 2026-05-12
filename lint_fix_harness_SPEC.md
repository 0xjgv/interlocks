# SPEC: Rule-Scoped Fix Harness and Budgeted Fix Optimizer

Status: Draft 0.1 — Phases 0 + 1 shipped (commit `c1d2282`); Phase 2 shipped; Phase 3 shipped; Phase 4 shipped; Phase 5 shipped.  
Audience: backend engineers, infra/tooling owners, reviewers  
Context: legacy Django backend, Python 3.12, Ruff-based custom lint harness  
Primary goal: unblock engineers without letting quality regress

---

## 1. Problem

The current lint adoption flow has three failure modes:

1. Engineers can be blocked by code they did not author.
2. Autofix can rewrite entire legacy files, causing unrelated review churn.
3. Style-preference rules can train engineers to ignore lint instead of trust it.

A recent unblock showed a better pattern:

```sh
for f in api_internal/views.py policies/admin.py \
         policies/agents/fp_learning_summarizer.py \
         policies/management/commands/schedule_fp_learning.py \
         policies/views.py; do
  uv run ruff check --select I001 --fix --force-exclude "$f"
done

make check ARGS=--fix
make ci
```

This worked because it was:

- rule-scoped: only `I001` import sorting was allowed to mutate files;
- file-scoped: only target files were passed to Ruff;
- formatter-scoped: formatting was applied through the existing changed-hunk range formatter;
- verified: final `make ci` passed;
- intentionally not broad: `make renovate` was skipped because it would have hit legacy findings outside the diff.

This spec generalizes that pattern.

---

## 2. Design Principle

Do not run every fixer directly on the developer's branch.

Instead:

1. Discover supported fixable rules.
2. Simulate each rule in isolation in a scratch worktree.
3. Measure churn, risk, and quality gain.
4. Classify candidate patches as auto-apply, patch escrow, advisory, or skipped.
5. Apply only candidates that pass a strict budget.
6. Verify the final result with `make ci`.

The default behavior must be non-mutating.

---

## 3. Goals

### 3.1 Engineer goals

- Preserve focused bugfix diffs.
- Avoid forcing legacy cleanup into feature PRs.
- Make `make check --fix` predictable.
- Provide a support command that can unblock an engineer without broad renovation.
- Reduce incentive to use `git commit --no-verify`.

### 3.2 Tooling goals

- Support rule-scoped fixes such as `I001`, `F401`, selected `UP*`, selected `PIE*`, etc.
- Keep unsafe fixes out of normal support flows.
- Record enough data to know which rules actually help.
- Add a later dynamic-programming optimizer to choose the best fix set under a churn/risk budget.

### 3.3 Review goals

- Keep semantic changes and mechanical changes distinguishable.
- Avoid surprise full-file rewrites.
- Make every applied fix explainable.

---

## 4. Non-goals

- No repo-wide formatting event in this project.
- No broad `ruff check --fix` support command.
- No `make renovate` in the engineer-unblock flow.
- No unsafe fixes in the default flow.
- No ML ranking in the first implementation.
- No individual engineer shaming based on bypass or lint metrics.
- No attempt to make Ruff's linter hunk-aware; `ruff check --fix` remains treated as file/rule scoped.

---

## 5. Definitions

### Changed hunk

A line range introduced or modified by the PR relative to `BASE`, usually `main`.

### Outside-diff churn

Any line changed by the fixer that does not intersect a changed hunk or an allowed mechanical region such as the import block related to an edited file.

### Candidate patch

The diff produced by applying one rule-scoped fixer to the target file set in a scratch worktree.

Example:

```text
candidate = rule I001 applied to {api_internal/views.py, policies/views.py}
```

### Patch escrow

A generated patch that is shown to the engineer but not applied by default.

### Support rule

A rule allowed in the engineer-unblock path after it has proven to be low-friction and safe enough for the configured mode.

### Auto-apply rule

A support rule whose candidate patch can be applied automatically if it passes all budgets and final verification.

### Renovation-only rule

A rule that may be useful for planned cleanup work but must not run in unblock flows.

---

## 6. User-facing commands

### 6.1 `make check --fix-plan`

Default non-mutating planning command.

```sh
make check --fix-plan
make check --fix-plan BASE=main
make check --fix-plan FILES="policies/views.py api_internal/views.py"
```

Behavior:

1. Detect changed files and changed hunks.
2. Discover candidate fixable Ruff diagnostics.
3. Simulate rule-scoped fixes in scratch worktrees.
4. Run the existing diff-scoped formatter on affected hunks.
5. Classify candidates.
6. Print a plan.
7. Write machine-readable output to `.lintfix/plan.json`.

Exit behavior:

- `0` if planning succeeded, even if no fixes are available.
- non-zero only for internal errors, invalid arguments, or dirty-state hazards that prevent safe planning.

Example output:

```text
Fix plan for main...HEAD

AUTO-APPLY ELIGIBLE
  I001   5 files   31 changed lines   4 outside-diff lines   risk=2
  W292   1 file     1 changed line    0 outside-diff lines   risk=0

PATCH ESCROW
  F401   2 files    3 changed lines   removes imports         risk=6
  UP007  3 files    9 changed lines   type syntax rewrite     risk=4

SKIPPED
  SIM    4 files   87 changed lines   outside-diff budget exceeded
  C4     2 files   42 changed lines   style-only, high churn
```

### 6.2 `make check --fix-safe`

Applies only auto-apply candidates that pass budget checks.

```sh
make check --fix-safe
```

Behavior:

1. Runs `--fix-plan` internally.
2. Applies only candidates whose mode is `auto` and whose measured cost is under budget.
3. Runs the existing diff-scoped formatter.
4. Runs `make ci`.
5. Leaves the tree changed only if final verification succeeds.

If final verification fails, the command must restore the original tree and write the failed patch to `.lintfix/failed.patch`.

### 6.3 `make check --fix-rule RULE=<code>`

Support escape hatch for a specific rule.

```sh
make check --fix-rule RULE=I001
make check --fix-rule RULE=F401 APPLY=0
make check --fix-rule RULE=UP007 APPLY=1
```

Default behavior:

- `APPLY=0`: show candidate patch and classification only.
- `APPLY=1`: apply only if the rule is allowed by config and the candidate passes budget checks.

This command replaces ad hoc shell loops for known support patterns.

### 6.4 `make check --fix-escrow`

Materializes escrow patches without applying them.

```sh
make check --fix-escrow
```

Output:

```text
.lintfix/escrow/I001.patch
.lintfix/escrow/F401.patch
.lintfix/escrow/UP007.patch
```

### 6.5 `make check --fix-optimize`

Phase 4 command. Uses dynamic programming to choose the best candidate subset under configured budgets.

```sh
make check --fix-optimize
make check --fix-optimize BUDGET=unblock
make check --fix-optimize BUDGET=renovation
```

Default behavior is non-mutating unless `APPLY=1` is passed.

---

## 7. Configuration

Add a small config file. Suggested name:

```text
.lintfix.toml
```

Example:

```toml
[tool.lintfix]
base = "main"
ruff_cmd = ["uv", "run", "ruff"]
ci_cmd = ["make", "ci"]
plan_dir = ".lintfix"

[tool.lintfix.budgets.unblock]
max_files = 5
max_changed_lines = 80
max_outside_diff_lines = 10
max_risk = 8
max_runtime_seconds = 45
allow_unsafe_fixes = false

[tool.lintfix.budgets.renovation]
max_files = 50
max_changed_lines = 2000
max_outside_diff_lines = 2000
max_risk = 30
max_runtime_seconds = 300
allow_unsafe_fixes = false

[tool.lintfix.rules.I001]
mode = "auto"
mutation_class = "import_sort"
risk = 2
allow_paths = ["**/*.py"]

[tool.lintfix.rules.W292]
mode = "auto"
mutation_class = "eof_newline"
risk = 0

[tool.lintfix.rules.F401]
mode = "escrow"
mutation_class = "import_delete"
risk = 6

[tool.lintfix.rules.UP007]
mode = "escrow"
mutation_class = "type_annotation_rewrite"
risk = 4

[tool.lintfix.rules.SIM]
mode = "advisory"
mutation_class = "control_flow_or_style"
risk = 10

[tool.lintfix.rules.C4]
mode = "advisory"
mutation_class = "collection_rewrite"
risk = 8

[tool.lintfix.rules.default]
mode = "advisory"
risk = 5
```

Config semantics:

- Exact rule codes override prefixes.
- Prefix rules override `default`.
- `mode = "auto"` still requires the candidate to pass budgets.
- `mode = "escrow"` never mutates the working tree unless explicitly requested.
- `allow_unsafe_fixes = false` is the default for all budgets.

---

## 8. Internal Architecture

### 8.1 Modules

```text
tools/lintfix/
  __init__.py
  cli.py
  git_diff.py
  ruff_discovery.py
  simulator.py
  patch_classifier.py
  patch_escrow.py
  formatter_ranges.py
  verifier.py
  optimizer.py
  report.py
  config.py
```

### 8.2 Responsibilities

#### `git_diff.py`

- Resolve `BASE`.
- List changed Python files.
- Parse changed hunks.
- Provide line-range membership tests.

#### `ruff_discovery.py`

- Run Ruff in JSON mode on changed files.
- Extract diagnostics, rule codes, and fix availability.
- Record fix applicability where Ruff reports it.
- Exclude unsafe fixes from normal support modes.

#### `simulator.py`

- Create scratch worktrees or temporary copies.
- Run one rule at a time:

```sh
uv run ruff check --select <RULE> --fix --force-exclude <files...>
```

- Never run broad `ruff check --fix` in support mode.
- Produce a candidate patch.

#### `formatter_ranges.py`

- Call the existing harness `_apply_format_ranges` on changed hunks only.
- Never run whole-file format in support mode unless the command is explicitly renovation-only.

#### `patch_classifier.py`

Classify candidate patches by:

- rule code;
- files touched;
- lines touched;
- outside-diff lines touched;
- whether imports were deleted;
- whether comments were deleted;
- whether assignments were deleted;
- whether control flow changed;
- whether type annotations changed;
- whether the patch overlaps risky paths such as migrations, settings modules, admin modules, or app loading code.

Classification output:

```text
auto
escrow
advisory
renovation_only
skip
```

#### `patch_escrow.py`

- Write unapplied patches to `.lintfix/escrow/`.
- Provide stable patch IDs.
- Allow explicit application by patch ID.

#### `verifier.py`

- Run lightweight checks during simulation if configured.
- Always run full `make ci` after applying any auto-fix candidate.
- Restore the original tree if verification fails.

#### `optimizer.py`

- Phase 4 dynamic-programming optimizer.
- Select candidate subset under configured budgets.
- Must remain explainable: print why each candidate was selected or rejected.

#### `report.py`

- Emit human-readable plan.
- Emit JSON plan for CI artifacts and future replay.

---

## 9. Candidate Patch Lifecycle

### Step 1: discover changed files

```text
base = merge-base(main, HEAD)
changed_files = git diff --name-only base...HEAD -- '*.py'
changed_hunks = git diff --unified=0 base...HEAD
```

### Step 2: discover fixable diagnostics

Run Ruff in non-mutating mode and parse JSON.

```sh
uv run ruff check --output-format json --force-exclude <changed_files...>
```

Candidate rules are the unique rule codes with available fixes.

### Step 3: simulate one rule at a time

For each candidate rule:

```sh
uv run ruff check --select <RULE> --fix --force-exclude <changed_files...>
```

Then run the existing range formatter only on changed hunks.

### Step 4: compute candidate metrics

For every candidate patch:

```text
rule_code
files_touched
changed_lines_total
changed_lines_inside_diff
changed_lines_outside_diff
import_deletes
assignment_deletes
comment_deletes
control_flow_edits
type_annotation_edits
risky_paths_touched
estimated_runtime_seconds
fix_applicability
```

### Step 5: classify

Candidate classification is based on config, measured churn, and risk rules.

Example:

```text
I001 + 5 files + 4 outside-diff lines + no CI failure -> auto
F401 + deletes imports -> escrow
SIM + 87 changed lines + style-only -> advisory
unsafe fix -> renovation_only or skip
```

### Step 6: apply only allowed candidates

In support mode:

1. Apply auto candidates only.
2. Re-run range formatter.
3. Run `make ci`.
4. Keep changes only if verification passes.

---

## 10. Risk Model

### 10.1 Base risk by mutation class

| Mutation class | Example rules | Default mode | Base risk |
|---|---|---:|---:|
| EOF newline | W292 | auto | 0 |
| import sort | I001 | auto | 2 |
| pure formatting range | formatter only | auto | 1 |
| import delete | F401 | escrow | 6 |
| unused variable cleanup | F841 | escrow | 7 |
| type annotation modernization | UP007, UP045 | escrow | 4 |
| collection rewrite | C4* | advisory | 8 |
| simplification/control-flow rewrite | SIM* | advisory | 10 |
| broad modernization | UP* prefix | advisory/renovation | 7 |
| unsafe fix | any | renovation/skip | 100 |

### 10.2 Path risk modifiers

| Path pattern | Modifier | Reason |
|---|---:|---|
| `**/migrations/**` | +10 | migration diffs are noisy and often generated |
| `**/settings*.py` | +6 | import/order side effects are more plausible |
| `**/admin.py` | +4 | import side effects and registration patterns |
| `**/apps.py` | +5 | app loading behavior can be subtle |
| `**/management/commands/**` | +2 | CLI surface, usually lower risk |
| tests | -2 | lower blast radius, easier to validate |

### 10.3 Churn risk

```text
risk += min(10, outside_diff_lines / 5)
risk += min(5, files_touched / 3)
risk += 10 if comments_deleted > 0
risk += 10 if control_flow_edits > 0
risk += 100 if unsafe_fix_seen
```

---

## 11. Dynamic Programming Implementation Phase

Dynamic programming should not be the first implementation. It depends on candidate metrics from earlier phases.

Use it after rule simulation and replay have produced enough data to estimate cost and benefit.

### 11.1 Optimization problem

Given candidate patches:

```text
C = {c1, c2, ..., cn}
```

Each candidate has:

```text
value(ci): estimated quality and unblock benefit
cost(ci): churn and risk vector
conflicts(ci): other candidates that cannot be applied together
```

Choose a subset `S` that maximizes total value while staying under budgets.

```text
maximize    Σ value(ci) * xi
subject to  Σ outside_diff_lines(ci) * xi <= B_outside
            Σ changed_lines(ci)      * xi <= B_lines
            Σ files_touched(ci)      * xi <= B_files
            Σ risk(ci)               * xi <= B_risk
            Σ runtime(ci)            * xi <= B_runtime
            xi + xj <= 1 for conflicting candidate pairs
            xi ∈ {0, 1}
```

This is a budgeted subset-selection problem. With one cost dimension, it is classic 0/1 knapsack. With multiple cost dimensions, use multi-dimensional DP with Pareto pruning.

### 11.2 Candidate value function

Initial deterministic value:

```text
value =
  8  * changed_line_findings_fixed
+ 10 * known_bug_contracts_fixed
+  5 * repeated_support_pattern_score
+  3 * review_noise_reduction_score
-  2 * advisory_style_only_penalty
```

Definitions:

- `changed_line_findings_fixed`: number of diagnostics on changed lines fixed by the candidate.
- `known_bug_contracts_fixed`: count of fixes tied to real incidents or review failures.
- `repeated_support_pattern_score`: higher when support engineers repeatedly perform this fix manually.
- `review_noise_reduction_score`: higher for fixes that reduce future review friction.
- `advisory_style_only_penalty`: applied to style-preference rules without incident backing.

### 11.3 Candidate cost vector

```text
cost = {
  outside_diff_lines,
  changed_lines_total,
  files_touched,
  risk,
  runtime_seconds,
}
```

Budgets are selected by mode:

```text
unblock:    strict budget, for engineer support
renovation: loose budget, for planned cleanup PRs
ci_advice:  no mutation, report only
```

### 11.4 Pareto-pruned DP algorithm

Pseudo-code:

```python
State = tuple[outside_lines, changed_lines, files, risk, runtime_bucket]

states = {
    zero_cost_state: Plan(value=0, candidates=[]),
}

for candidate in candidates:
    next_states = dict(states)

    for state, plan in states.items():
        if plan.conflicts_with(candidate):
            continue

        new_state = state + discretize(candidate.cost)
        if exceeds_budget(new_state, budget):
            continue

        new_plan = plan.add(candidate)

        if new_plan.value > next_states.get(new_state, empty_plan).value:
            next_states[new_state] = new_plan

    states = prune_dominated_states(next_states)

return max(states.values(), key=lambda plan: plan.value)
```

A state `A` dominates state `B` when:

```text
A.value >= B.value
A.cost <= B.cost in every dimension
A is strictly better in at least one dimension
```

Dominated states are discarded.

### 11.5 Conflict handling

Candidates conflict if they:

- edit overlapping hunks;
- edit the same import block in incompatible ways;
- delete lines another candidate rewrites;
- depend on a rule ordering not represented in the candidate patch;
- fail to apply cleanly after a previously selected candidate.

Initial implementation may use conservative conflict detection:

```text
same file + overlapping changed line range => conflict
same file + both edit import block => conflict unless same rule family
```

After DP selection, the harness must still apply selected candidates sequentially in a fresh worktree and verify the final patch. If a candidate no longer applies, drop the lower-value conflicting candidate and rerun optimization.

### 11.6 DP output

Example:

```text
Optimized fix plan: budget=unblock

SELECTED
  I001   value=41 cost={outside=4, lines=31, files=5, risk=2}
  W292   value=8  cost={outside=0, lines=1,  files=1, risk=0}

NOT SELECTED
  F401   value=16 cost={outside=1, lines=3, files=2, risk=6}
         reason: risk budget would be exceeded after selected candidates
  SIM    value=9  cost={outside=39, lines=87, files=4, risk=18}
         reason: outside-diff budget exceeded
```

### 11.7 Why DP instead of ML first

DP is explainable and works with small candidate sets. It can say exactly why a rule was selected or rejected.

ML should be considered later only after enough labeled history exists:

```text
accepted
reverted
caused CI failure
caused review complaint
required manual support
```

---

## 12. Implementation Phases

### Phase 0: harden the current unblock pattern ✅ Shipped (commit `c1d2282`)

Deliverables:

- [x] Replace ad hoc `uvx ruff` usage with repo-pinned `uv run ruff` or another repo-pinned command. *(uses `uvx --from ruff==<version>` via `runner.uvx_tool` + `cfg.tool_version("ruff")`)*
- [x] Add an idempotent EOF newline helper instead of repeated `printf '\n' >> file`. *(`lintfix/eof_newline.py::ensure_trailing_newline`)*
- [x] Add a documented `I001` support runbook. *(README "Support Flow: Rule-Scoped Unblock")*
- [x] Ensure support commands always run `make ci` at the end. *(default `--verify-cmd` is `interlocks ci`)*

Acceptance criteria:

- [x] A support engineer can run a documented `I001` fix without using broad `make renovate`.
- [x] The command does not apply unsafe fixes. *(`check_budget` blocks `unsafe=True`; ruff invoked without `--unsafe-fixes`)*
- [x] The command preserves unrelated legacy findings outside the diff. *(`--select=<RULE>` scopes mutation to the single rule)*

### Phase 1: rule-scoped support harness ✅ Shipped (commit `c1d2282`)

Deliverables:

- [x] Implement `make check --fix-rule RULE=<code>`. *(shipped as `interlocks fix-rule --rule=<code>`)*
- [x] Implement scratch worktree simulation. *(via ruff `--diff` — same non-mutating invariant; `lintfix/simulate.py`)*
- [x] Implement patch classification for:
  - [x] `I001`
  - [x] `W292`
  - [x] `F401`
  - [x] selected `UP*` *(`UP007`, `UP045` in catalog; `UP*` prefix fallback for the rest)*
- [x] Implement patch escrow output. *(`lintfix/escrow.py` → `.lintfix/escrow/<rule>.patch`)*

Acceptance criteria:

- [x] `make check --fix-rule RULE=I001 APPLY=0` produces a patch preview and does not mutate the working tree. *(`test_plan_mode_does_not_mutate_tree`)*
- [x] `make check --fix-rule RULE=I001 APPLY=1` applies only if budgets pass and `make ci` passes. *(`test_apply_mode_mutates_on_clean_verify` + `test_apply_mode_restores_tree_on_verify_failure`)*
- [x] `F401` defaults to escrow, not auto-apply. *(`test_f401_defaults_to_escrow_and_writes_patch`)*

### Phase 2: exhaustive fix simulation ✅ Shipped

Deliverables:

- [x] Implement `make check --fix-plan`. *(shipped as `interlocks fix-plan`)*
- [x] Discover fixable diagnostics from Ruff JSON output. *(`lintfix/discover.py::discover_fixable_rules` parses `ruff check --output-format=json`)*
- [x] Simulate each candidate rule independently. *(reuses `lintfix/simulate.py::simulate_rule` per rule; non-mutating `--diff`)*
- [x] Produce `.lintfix/plan.json`. *(`lintfix/plan.py::write_plan_json`; schema matches section 13)*
- [x] Print human-readable classification. *(grouped `AUTO-APPLY ELIGIBLE` / `PATCH ESCROW` / `ADVISORY` / `SKIPPED` blocks)*

Acceptance criteria:

- [x] The planner can run all candidate rules in simulation without mutating the developer tree. *(`test_fix_plan_does_not_mutate_tree`)*
- [x] Every candidate reports files touched, changed lines, outside-diff lines, and risk. *(`test_fix_plan_writes_json_with_spec_schema` checks the full per-candidate key set)*
- [x] Unsupported or unsafe candidates are clearly skipped. *(`_unsafe_skip_classification` short-circuits unsafe-only rules to `mode=skip` with `reason="unsafe fix not allowed in default mode"`; `test_build_plan_marks_unsafe_only_rule_as_skip`)*

### Phase 3: offline replay and Pareto frontier ✅ Shipped

Deliverables:

- [x] Replay the planner against the last N merged PRs. *(shipped as `interlocks fix-replay`; `lintfix/replay.py::replay_history` walks first-parent commits in temporary git worktrees)*
- [x] Produce rule-level statistics:
  - [x] PRs helped; *(`stats.RuleStats.prs_helped` = observations whose classification ≠ `skip`)*
  - [x] median changed lines; *(`stats.RuleStats.median_changed_lines` via linear-interpolation `quantile`)*
  - [x] p95 changed lines; *(`stats.RuleStats.p95_changed_lines`)*
  - [x] median outside-diff lines; *(`stats.RuleStats.median_outside_diff_lines`)*
  - [x] p95 outside-diff lines; *(`stats.RuleStats.p95_outside_diff_lines`)*
  - [ ] CI failures; *(deferred — Phase 5 will record CI verdicts in plan history; replay does not re-run CI per commit)*
  - [x] patch rejection/revert signals if available. *(`stats.RuleStats.revert_signal`; `replay._find_revert` scans `<commit>..<base>` for the canonical `This reverts commit <sha>` body)*
- [x] Produce a Pareto frontier of rules by quality gain vs churn/risk. *(`stats._pareto_frontier`: maximize `prs_helped`, minimize `p95_outside_diff_lines`; unsafe rules can't dominate safe rules)*

Acceptance criteria:

- [x] The team can justify why a rule is auto, escrow, advisory, or renovation-only using measured history. *(`.lintfix/replay.json` carries per-rule `recommended_mode` + `rationale` plus the full sample list per commit; `test_cmd_fix_replay_serializes_recommendation_payload`)*
- [x] Broad style families cannot enter auto mode without evidence. *(prefix-fallback rules require `_MIN_OBS_PREFIX=10` observations AND frontier membership AND an explicit catalog entry before any auto-promotion fires; `test_aggregate_refuses_to_promote_prefix_fallback_rule`)*

### Phase 4: dynamic-programming optimizer ✅ Shipped

Deliverables:

- [x] Implement `make check --fix-optimize`. *(shipped as `interlocks fix-optimize`; `tasks/fix_optimize.py::cmd_fix_optimize` reuses `plan.build_plan` then runs `optimize.optimize`)*
- [x] Use candidate metrics from Phase 2 and value estimates from Phase 3. *(`optimize.candidates_from_plan` reads `PlannedCandidate` cost dims; `--stats=.lintfix/replay.json` hydrates `RuleStats` for the support-pattern component of `value_for`)*
- [x] Implement multi-dimensional DP with Pareto pruning. *(`optimize._search` iterates candidates, branching include/exclude on each; `_prune_dominated` discards plans dominated in all four cost dims by a plan of ≥ equal value)*
- [x] Support at least two budget profiles: *(both already exist in `budgets._PROFILES`; the optimizer reads the active profile via `budgets.profile(name)`)*
  - [x] `unblock`
  - [x] `renovation`
- [x] Explain every selected and rejected candidate. *(`_rejection_reason` maps each unselected candidate to one of `unsafe fix not allowed`, `policy mode is <X>`, `conflicts with selected rule <Y>`, `would exceed <dim> budget`, or `displaced by higher-value selection`; emitted in both the printed plan and `.lintfix/optimize.json`)*

Acceptance criteria:

- [x] Given a synthetic candidate set, the optimizer selects the maximum-value subset under budget. *(`test_optimize_picks_max_value_subset_under_budget`: anti-greedy knapsack where greedy-by-value picks A alone but DP picks B+C)*
- [x] Given real candidate patches, the optimizer never selects unsafe fixes in `unblock` mode. *(`Budget.allow_unsafe_fixes=False` propagates via `classify.classify(unsafe=True) → mode="skip"`; `candidates_from_plan` then marks the candidate `selectable=False`; `test_fix_optimize_never_selects_unsafe_in_unblock` covers it end-to-end)*
- [x] The final selected patch is re-applied in a fresh worktree and verified with `make ci`. *(`verify.apply_many_with_verify` snapshots the union of touched files, applies each selected rule sequentially, runs the verifier, and restores the snapshot on any failure; `test_fix_optimize_apply_mutates_on_clean_verify` + `test_fix_optimize_apply_restores_tree_on_verify_failure`)*

### Phase 5: CI integration and adoption ✅ Shipped

Deliverables:

- [x] Add CI artifact for `.lintfix/plan.json`. *(bundled `interlocks/defaults/github_workflow.yml` now adds an `actions/upload-artifact@v4` step uploading the entire `.lintfix/` directory — plan, optimize, replay, metrics, and escrow patches — under `lintfix-${{ github.run_id }}`, with `if-no-files-found: ignore` so runs without candidates stay green)*
- [x] Add optional PR annotation summarizing suggested fixes. *(shipped as `interlocks fix-annotate`; `tasks/fix_annotate.py` reads `.lintfix/plan.json` (or `.lintfix/optimize.json` with `--source=optimize`) and emits one workflow command per `(rule, file)`: `::notice file=<file>,line=1::[<rule>] auto|escrow: ...` for auto/escrow, `::warning file=<file>,line=1::` for advisory, skipped candidates emit nothing)*
- [x] Add aggregate metrics: *(shipped as `interlocks fix-metrics`; `tasks/fix_metrics.py` rolls up the per-run JSON files into `.lintfix/metrics.json` with `generated_at`, a `sources` truthtable, and per-section summaries)*
  - [x] planner runs; *(each CI run uploads its own `metrics.json` artifact; cross-run aggregation is by external collection of artifacts, keeping interlocks stateless and per-author-blind)*
  - [x] auto fixes applied; *(`plan.by_classification.auto` plus `optimize.selected` count)*
  - [x] escrow patches generated; *(`plan.escrow_rules` list and `plan.by_classification.escrow` count)*
  - [ ] CI failures after fixes; *(deferred — would require a persistent counter store across runs; for now consumers can fold artifact-level pass/fail into the external aggregation)*
  - [x] average outside-diff churn; *(`plan.avg_outside_diff_lines` + `plan.p95_outside_diff_lines` via linear-interpolation quantile matching `stats.quantile`)*
  - [x] common skipped rules. *(`plan.skipped_rules` sorted list, plus `optimize.rejection_reasons` Counter for "policy mode is escrow", "would exceed <dim> budget", "displaced by higher-value selection", etc.)*

Acceptance criteria:

- [x] CI does not fail because of advisory fix suggestions. *(every Phase 5 step in the bundled workflow runs with `if: always()`; `fix-annotate` emits only `::notice::` / `::warning::` lines — never `::error::` — and exits 0 even when `.lintfix/plan.json` is missing; `test_missing_plan_file_exits_zero_with_no_annotations`)*
- [x] Metrics are aggregate and used to tune policy, not to police individuals. *(no author or commit-author fields anywhere in the `metrics.json` schema; `fix-metrics` reads only `.lintfix/*.json` outputs which are themselves per-rule, not per-engineer; `test_summarize_plan_groups_classifications` and friends pin the rollup keys)*
- [x] Developers can still land focused fixes without broad cleanup. *(the Phase 5 steps are pure advisory — no mutation, no gate; the existing `fix-rule --apply` / `fix-optimize --apply` paths remain the only way the harness ever mutates the tree, and both keep the rule-scoped, budgeted, verify-or-restore invariants from earlier phases)*

---

## 13. Report JSON Schema

Example `.lintfix/plan.json`:

```json
{
  "base": "main",
  "head": "abc123",
  "mode": "unblock",
  "ruff_version": "0.x.y",
  "candidates": [
    {
      "id": "I001:api_internal/views.py:policies/views.py",
      "rule": "I001",
      "mode": "auto",
      "classification": "auto",
      "mutation_class": "import_sort",
      "files_touched": 2,
      "changed_lines_total": 17,
      "changed_lines_inside_diff": 14,
      "changed_lines_outside_diff": 3,
      "risk": 2,
      "value": 29,
      "unsafe": false,
      "patch_path": ".lintfix/escrow/I001.patch",
      "selected_by_optimizer": true,
      "rejection_reason": null
    },
    {
      "id": "F401:policies/admin.py",
      "rule": "F401",
      "mode": "escrow",
      "classification": "escrow",
      "mutation_class": "import_delete",
      "files_touched": 1,
      "changed_lines_total": 1,
      "changed_lines_inside_diff": 1,
      "changed_lines_outside_diff": 0,
      "risk": 6,
      "value": 8,
      "unsafe": false,
      "patch_path": ".lintfix/escrow/F401.patch",
      "selected_by_optimizer": false,
      "rejection_reason": "escrow_only"
    }
  ]
}
```

---

## 14. Testing Plan

### 14.1 Unit tests

- Parse changed hunks from git diff.
- Detect inside-diff vs outside-diff line changes.
- Classify import sort patches.
- Classify import deletion patches.
- Classify comment deletion patches.
- Classify type annotation rewrites.
- Detect overlapping patch conflicts.
- Verify DP optimizer on synthetic candidate sets.
- Verify Pareto pruning preserves optimal candidates.

### 14.2 Integration tests

Create fixtures for:

1. Legacy violation outside the diff.
2. Changed hunk with `I001` import sorting.
3. Changed hunk with `W292` EOF newline.
4. `F401` unused import with possible side effect.
5. `UP007` type annotation rewrite.
6. `SIM` simplification that causes too much outside-diff churn.
7. Formatter range application that does not rewrite whole file.
8. Candidate conflict between two rule patches.

Expected results:

- `I001` can auto-apply when budgets pass.
- `F401` goes to escrow by default.
- `SIM` goes advisory or skipped when churn is high.
- Unsafe fixes never apply in unblock mode.
- `fix-plan` never mutates the working tree.
- `fix-safe` restores the tree if `make ci` fails.

### 14.3 Replay tests

Replay at least 25 historical PRs before enabling new auto rules.

For each candidate rule, report:

```text
rule
PRs_with_candidate
PRs_helped
median_changed_lines
p95_changed_lines
median_outside_diff_lines
p95_outside_diff_lines
CI_failure_rate
recommended_mode
```

---

## 15. Rollout Plan

### Stage 1: support-only

- Tooling/support engineers run `fix-rule` manually.
- No developer-facing gate changes.
- Collect candidate data.

### Stage 2: developer opt-in

- Expose `make check --fix-plan` and `make check --fix-safe`.
- Default is still non-mutating for planning.
- Publish examples for common unblock cases.

### Stage 3: advisory CI artifact

- CI uploads `.lintfix/plan.json`.
- PRs show suggestions but do not fail on advisory findings.

### Stage 4: auto-apply narrow support rules

- Allow low-risk rules such as `I001` and `W292` to auto-apply in support flow.
- Require final `make ci`.

### Stage 5: optimized selection

- Enable `fix-optimize` after replay confirms cost/value estimates.
- Keep optimizer non-mutating by default.

---

## 16. Success Metrics

Measure at aggregate level:

```text
hook bypass rate
lint failure rate
format failure rate
fix-plan usage
fix-safe usage
auto-fixes applied
escrow patches generated
mean outside-diff churn
p95 outside-diff churn
CI failures after autofix
support tickets requiring manual lint intervention
review comments about unrelated mechanical churn
```

The most important metric is not raw violation count. It is whether engineers can land focused changes without bypassing the gate while the codebase still trends cleaner.

---

## 17. Initial Rule Recommendations

Initial modes before replay:

| Rule or family | Initial mode | Rationale |
|---|---|---|
| `I001` | auto | Known support pattern; low mutation scope; still measured by churn budget |
| `W292` | auto | One-line mechanical fix |
| `F401` | escrow | May delete imports with side effects or public re-export intent |
| `F841` | escrow | Can hide assignment side-effect questions |
| selected `UP*` | escrow | Often safe but usually modernization, not unblock-critical |
| `PIE*` | advisory/escrow | Rule-dependent; needs replay data |
| `C4*` | advisory | Can rewrite collection logic and create review noise |
| `SIM*` | advisory | Often style/control-flow preference; high annoyance risk |
| unsafe fixes | renovation-only/skip | Not acceptable in unblock mode |

No family should move to auto mode as a family. Promote exact rules after replay.

---

## 18. Open Questions

1. What should the initial unblock budget values be?
2. Should import sorting be auto in `admin.py`, `apps.py`, and settings modules, or escrow there?
3. How many historical PRs are enough before promoting a new auto rule?
4. Should `make ci` run per candidate or only after the selected aggregate patch?
5. Should the optimizer maximize per-rule value or per-patch-group value?
6. Should support engineers be allowed to override escrow mode with `APPLY=1`?
7. Should CI publish advisory suggestions as annotations, artifacts, or both?

---

## 19. Core Invariant

The support flow must never make the engineer responsible for unrelated legacy cleanup.

Every automated fix must satisfy one of these conditions:

1. It directly touches code the PR changed.
2. It is a small, explainable mechanical edit required to make changed code pass.
3. It is explicitly separated into patch escrow or a renovation path.

If a fix violates that invariant, it does not belong in the unblock flow.
