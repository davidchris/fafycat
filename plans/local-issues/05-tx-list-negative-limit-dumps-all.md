# [CLI] tx list --limit -1 dumps the entire table

**Severity:** blocker
**Source:** QA of issue #26 (`plans/qa-issue-26-findings.md` finding 5)

## Repro

```bash
FAFYCAT_DATA_DIR=$QA_DIR uv run fafycat tx list --limit -1
```

## Observed

exit 0. Response: `total_count = 260`, all 260 transaction objects
(~110 KB stdout against the QA seed). Against a real DB this would be
arbitrarily large.

## Expected

PRD US 4: default 20, cap 500. Whole point: prevent agent from blowing
context window with one mistyped flag.

Negative `--limit` should reject at parse time (exit 2) or emit JSON
error (exit 1). Never silently return all rows.

## Proposed fix direction

Argparse `type=` enforcing `1 <= n <= 500`. Or guard
`get_transactions_with_pagination` so non-positive raises.

Same fix family as finding 1 (`--limit 0` ZeroDivisionError) — single
validator covers both.
