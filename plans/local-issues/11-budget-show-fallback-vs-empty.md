# [CLI] budget show <year> with no data returns fallback budgets, not empty

**Severity:** friction
**Source:** QA of issue #26 (`plans/qa-issue-26-findings.md` finding 11)

## Repro

```bash
uv run fafycat budget --data-dir $QA_DIR show 9999
```

## Observed

exit 0. Full per-category budget list, every entry has
`has_year_specific=false` and the category's default `fallback_budget`.

## Expected

PRD: "not found ⇒ empty result, exit 0".

Current contract arguably defensible (fallback budgets do apply to any
year), but agent expecting empty `budgets: []` for never-budgeted year
will misinterpret.

## Proposed fix direction

Decide which contract PRD intends, document in SKILL.md. Either:
- Filter to years with explicit budgets (return empty when none),
- Or annotate response with top-level
  `has_year_specific_budgets: bool` so agent can branch.
