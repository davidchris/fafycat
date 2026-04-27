# Local issue queue — Issue #26 QA

13 markdown files. One issue each, except `12-skill-md-drift.md` which
bundles three small SKILL.md drift items (split if desired).

Source: `plans/qa-issue-26-findings.md` (full QA report, run 2026-04-27).

## Blockers (6)

1. `01-tx-list-limit-zero-zerodivision.md` — `tx list --limit 0` traceback.
2. `02-analytics-yoy-bad-years-traceback.md` — bad `--years` raises ValueError.
3. `03-analytics-top-bad-month-traceback.md` — `--month 13` raises ValueError.
4. `04-data-dir-flag-positioning.md` — `--data-dir` only at group level.
5. `05-tx-list-negative-limit-dumps-all.md` — `--limit -1` dumps full table.
6. `06-malformed-toml-traceback.md` — bad TOML in `FAFYCAT_CONFIG` traceback.

## Friction (5)

7. `07-error-contract-inconsistent.md` — argparse vs JSON exit codes mixed.
8. `08-cat-list-bare-array.md` — `cat list` bare array, no envelope.
9. `09-analytics-breakdown-type-unvalidated.md` — `--type bogus` accepted silently.
10. `10-config-loaded-multiple-times.md` — config loader runs 3× per invocation.
11. `11-budget-show-fallback-vs-empty.md` — unknown year returns fallbacks.

## Nits (2)

12. `12-skill-md-drift.md` — SKILL.md positioning hint, field list, default docs.
13. `13-cat-list-inactive-coverage.md` — `--include-inactive` test coverage gap.
