# How To Use Budgeted Lint And Format Fixes

This guide walks through the real case this feature is meant to handle:
you make a small product edit in a Python file that already has unrelated
lint or formatting debt, and you want interlocks to fix only the safe,
review-sized part of the change.

The default stage behavior is conservative. `interlocks check` and
`interlocks pre-commit` size their lint/format mutation budget from your
author diff. Broad cleanup is opt-in through renovation mode.

## What You Will See

- A small edit does not trigger broad Ruff formatting churn.
- `.lintfix/optimize.json` explains which candidates were selected or skipped.
- Deleting Python files increases the review budget, but deleted files are not
  passed to Ruff mutation commands.
- Renovation mode applies broader formatting intentionally.

## Fast Proof In This Repository

Run the real-Ruff e2e scenarios:

```bash
uv run python tools/run_lintfix_e2e.py \
  --keep-going \
  --scenario=budget-small-format-skip \
  --scenario=budget-renovation-format \
  --scenario=budget-deleted-file
```

Expected result:

```text
lint-fix e2e
  [ok] budget-small-format-skip: ok
  [ok] budget-renovation-format: ok
  [ok] budget-deleted-file: ok
```

Those scenarios create temporary git repositories under `.factory/playgrounds/`
and run the same CLI path a project uses. They are not mock-only tests.

## Daily Use Case

Imagine this file already exists on `main` with old formatting debt:

```python
def alpha() -> int:
    return 1


def beta() -> int:
    return 2
```

You only change the behavior of `beta`:

```python
def beta() -> int:
    return 22
```

Ruff format could clean up the whole file, but that would mix your product edit
with unrelated cleanup. Run the normal local gate:

```bash
uv run interlocks check
```

For direct inspection without running the full stage, run the optimizer:

```bash
uv run interlocks fix-optimize \
  --base=HEAD \
  --budget=dynamic \
  --apply \
  --verify-cmd="python -c pass"
```

Then inspect the artifact:

```bash
python -m json.tool .lintfix/optimize.json
```

Look for:

- `budget: "dynamic"`
- `author_cost`: the measured size of your diff
- `active_budget.max_outside_diff_lines`: often `0` for tiny edits
- `not_selected[].reason`: for broad format churn, usually
  `would exceed outside-author-hunk budget`
- `not_selected[].cost`: the exact cost vector that exceeded the budget

That means interlocks saw the format candidate, measured it, and skipped it
because it touched lines outside your edit.

## Intentional Cleanup

When the PR is specifically for cleanup, opt into renovation mode:

```bash
uv run interlocks check --renovate
```

Or inspect/apply only the optimizer path:

```bash
uv run interlocks fix-optimize \
  --base=HEAD \
  --budget=renovation \
  --apply \
  --verify-cmd="python -c pass"
```

Now `.lintfix/optimize.json` should show the format candidate under
`selected`, and the working tree should contain the broader Ruff formatting.

Use this when the PR title and review intent are cleanup-oriented. Do not use it
to hide unrelated churn inside a feature fix.

## Deleted Files

If your change deletes a Python file, interlocks counts those deleted lines in
`author_cost`. That makes the budget proportional to the review surface.

Deleted files are excluded from the Ruff mutation file list, so Ruff is not
asked to fix paths that no longer exist. In `.lintfix/optimize.json`, confirm:

- `author_cost` includes the deletion-heavy change.
- No `selected[].files` or `not_selected[].files` entry contains the deleted
  path.

The e2e scenario `budget-deleted-file` verifies this behavior against a
temporary git repository.

## Reading The Artifact

The optimizer writes `.lintfix/optimize.json` on every run. The most useful
fields are:

```json
{
  "budget": "dynamic",
  "author_cost": 3,
  "active_budget": {
    "max_changed_lines": 5,
    "max_outside_diff_lines": 0
  },
  "selected": [],
  "not_selected": [
    {
      "rule": "FORMAT:src/example.py",
      "kind": "format",
      "cost": {
        "changed_lines": 6,
        "outside_diff": 5,
        "files": 1,
        "risk": 2
      },
      "reason": "would exceed outside-author-hunk budget"
    }
  ]
}
```

Interpretation:

- `selected` is what interlocks would apply, or did apply with `--apply`.
- `not_selected` is not noise; it is the audit trail for skipped candidates.
- `outside_diff` means lines changed by the tool outside your author hunks.
- `risk` is a conservative signal for broader or less localized mutations.

## Which Command To Use

Use the stage command for normal development:

```bash
uv run interlocks check
```

Use direct optimizer inspection when diagnosing a specific lint/format decision:

```bash
uv run interlocks fix-optimize --base=origin/main --budget=dynamic
```

Use renovation only for deliberate cleanup PRs:

```bash
uv run interlocks check --renovate
```

Before pushing, keep the usual gate green:

```bash
uv run interlocks check
```
