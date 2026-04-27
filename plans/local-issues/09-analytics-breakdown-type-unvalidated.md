# [CLI] analytics breakdown --type accepts unknown values silently

**Severity:** friction
**Source:** QA of issue #26 (`plans/qa-issue-26-findings.md` finding 9)

## Repro

```bash
uv run fafycat analytics --data-dir $QA_DIR breakdown --type bogus
uv run fafycat analytics --data-dir $QA_DIR breakdown --type expense
```

## Observed

exit 0. Response:
```json
{"categories": [], "summary": {"total_amount": 0, "total_categories": 0},
 "date_range": {...}}
```

Same shape as a valid type with no matches. Actual valid set:
`income | saving | spending` (from `cat list .[].type`).

## Expected

PRD US 12: "optionally filtered by category type". Agent that asks for
`expense` gets successful empty response and concludes there is no
spending data — false negative.

## Proposed fix direction

`choices=["income", "saving", "spending"]` in argparse. Document
allowed set in `--help` and SKILL.md.
