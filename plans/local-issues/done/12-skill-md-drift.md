# [skill] SKILL.md drift: positioning, fields, undocumented defaults

**Severity:** nit (bundle of three small drift items)
**Source:** QA of issue #26 (`plans/qa-issue-26-findings.md` findings 12, 13, 14)

Three small drift items in `.claude/skills/fafycat/SKILL.md`. Bundled
because they all live in the same template file and are likely a single
PR; split if you want to file separately.

## 12a. `--data-dir PATH` line doesn't show working position

`SKILL.md` line 83 lists `--data-dir PATH` flag without example. Agent
will type `fafycat tx list --data-dir ...` first → fails (see blocker
finding 4 / `04-data-dir-flag-positioning.md`).

**Fix direction:** Add one example showing positioning, e.g.
`fafycat tx --data-dir /path list --month 2025-01`. Or fix blocker 4
so any position works and keep SKILL.md as-is.

## 12b. `cat list` field list incomplete

SKILL.md line 19 lists `id, name, type, is_active, budget`. Actual
response keys: `budget, created_at, id, is_active, name, type,
updated_at`.

**Fix direction:** Either document the timestamp fields, or drop them
from the response if not useful for agents. Tied to envelope decision
in finding 8 / `08-cat-list-bare-array.md`.

## 12c. `analytics top` defaults to current month silently

`fafycat analytics top` with no `--year`/`--month` returns top
transactions for current month. Convenient but undocumented in
SKILL.md and `--help`.

**Fix direction:** Document defaults in `--help` and SKILL.md, or make
`--year`/`--month` required.

## Expected (across all three)

PRD US 30: skill content is single source of truth, versioned with
release.
PRD US 31: skill body lists actual surface, examples drawn from real
CLI.
PRD US 34: each subcommand `--help` includes ≥1 example.

Current SKILL.md is close but drifts in three places.
