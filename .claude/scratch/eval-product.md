# Product eval: shipped FAQ + onboarding

## A. README FAQ (lines 235–259) — 6 entries shipped vs 8 planned

All 6 entries pass skim test (≤120 words). All "planned" notes flipped to active-tense for shipped features (`config show`, `--skip`, `setup --ci=github`). No blob URLs, no broken anchors — entries reference commands only.

| # | Title | Accurate vs code | Notes |
|---|---|---|---|
| Q1 | Style rules bundled | YES — names match `tasks/config.py:42-54` | Strong; closes (a). |
| Q2 | Defaults extend? | YES — replace-not-extend matches `defaults_path.py:91-115` | Tightest entry, explicit footgun. |
| Q3 | Ignore/skip | YES — `--skip`, `INTERLOCKS_SKIP`, `[tool.interlocks] skip` all live; "unknown labels exit 2" matches `config.py:802-810` | Closes (b). |
| Q4 | Setup vs CI | YES — `setup --ci=github [--check]` shipped (`tasks/setup.py:35-65`) | Closes (c). |
| Q5 | Python versions | **PARTIAL** — text says "3.11, 3.12, 3.13" but `pyproject.toml:12,14` classifiers list only 3.11 + 3.13 (3.12 absent) | Add `Python :: 3.12` classifier. |
| Q6 | Production-ready | YES — honest about scope | Absorbs planned "is it ready?" bonus. |

**Missing planned entries:**
- "Why 'interlocks'?" — branding curiosity. **Drop, not adoption-critical.**
- "How to run only changed-file gates?" (`--changed`) — partially folded into Q3, but fast-iteration is a different JTBD from skip. **Add a 3-sentence entry.**

## B. Agents block (`agents_block.md` 18 lines + AGENTS.md 44 lines)

| Agent must know | `agents_block.md` | `AGENTS.md` | Verdict |
|---|---|---|---|
| (a) Blocking vs advisory | Generic line 17 | absent | Partial — agent must guess which gate is which. Plan §3 prescribed a per-gate matrix. |
| (b) Override precedence | **absent** | absent | Hard miss. README has it (line 222–227) but block doesn't point there. Agent won't know `CLI > [tool.interlocks] > preset > bundled`. |
| (c) Escalation rules | **absent** | weak ("prefer interlocks commands") | Plan §3 prescribed: ask user before lowering threshold, switching preset, `--no-verify`, disabling enforcement. **Real risk:** agent silently drops `coverage_min` to pass. |
| (d) `--skip` exists | **absent** | absent | New shipped feature invisible to agents. |

Block grew 13→18 lines but skipped the three highest-leverage additions.

## C. JTBD coverage matrix

| Concern | README FAQ | AGENTS.md | Help/config | Score |
|---|---|---|---|---|
| (a) Opaque defaults | Q1+Q2 | absent | `config show <tool>` exposes resolved source | obvious <30s |
| (b) Skipping | Q3 | **absent** | `config` shows resolved skip list | obvious <30s for humans, absent for agents |
| (c) Automation | Q4 | command listed, no when-to-use | `setup --check` + `setup --ci=github --check` | findable |
| (d) Python floor | Q5 | "3.11+" stated | n/a | obvious <30s |

## D. Highest-leverage remaining edits

1. **Agents-block v2 finish: add the missing 8 lines from onboarding-flow §3** — blocking-vs-advisory matrix, precedence, escalation, `--skip` example. Single largest remaining adoption gap. Agents are first-class users; the block is their only contract.
2. **Add `--changed` FAQ entry** (≤3 sentences) — fast-iteration JTBD currently buried in Q3.
3. **Add `Python :: 3.12` classifier** to `pyproject.toml:12-14` — Q5 promises it, classifiers omit it.
4. **Drop "Why 'interlocks'?"** — branding, not adoption.
5. **Verify Q3 skip-warning copy** — text must make clear the gate did NOT run (vs. ran-but-didn't-fail).

No overpromise found in shipped FAQ. All "planned → active" flips landed.

## E. Maturity banner — ship without it?

**Recommendation: SHIP without it. Severity of skipping: low.**

- Q6 "production-ready?" already addresses maturity for anyone who reads README.
- Banner targets users who skip docs — real cohort, but bad-first-impression risk, not broken-adoption risk.
- Agents-block gaps (B) are ~5× higher leverage. Spend the next iteration there.
- Add banner in v0.2.x once `.seen` infra exists.

**Caveat:** if release marketing claims "agent-ready," the §B gaps weaken that claim. Either fix the block or soften the copy.
