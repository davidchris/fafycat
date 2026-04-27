# [CLI] cat list returns bare array; inconsistent with other subcommands' envelope

**Severity:** friction
**Source:** QA of issue #26 (`plans/qa-issue-26-findings.md` finding 8)

## Repro

```bash
uv run fafycat cat --data-dir $QA_DIR list
```

## Observed

Top-level value: raw JSON array (length 17 in QA seed).

## Expected

Every other read-only subcommand wraps results in object envelope:
- `tx list` → `{transactions, total_count, has_next, skip, limit}`
- `analytics breakdown` → `{categories, summary, date_range}`
- `analytics monthly` → `{year, monthly_data, yearly_totals}`
- `budget show` → `{year, budgets, total_categories}`
- etc.

Agent that learned envelope shape elsewhere will reach for
`.categories` / `.total_count` and get `null`.

PRD US 3 (uniform JSON) doesn't strictly mandate envelope, but de-facto
convention is everywhere else.

## Proposed fix direction

Wrap as `{"categories": [...], "total_count": N}`. Update SKILL.md
`cat list` section.
