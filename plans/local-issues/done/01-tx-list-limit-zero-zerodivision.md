# [CLI] tx list --limit 0 throws ZeroDivisionError instead of validation error

**Severity:** blocker
**Source:** QA of issue #26 (`plans/qa-issue-26-findings.md` finding 1)

## Repro

```bash
FAFYCAT_DATA_DIR=$QA_DIR uv run fafycat tx list --limit 0
```

## Observed

```
File "src/fafycat/api/services.py", line 219, in get_transactions_with_pagination
    page = (skip // limit) + 1
ZeroDivisionError: integer division or modulo by zero
exit=1
```

Python traceback to stderr. No JSON error envelope.

## Expected

PRD US 4: `--limit` cap 1–500.
PRD US 17: runtime errors emitted as `{"error": "..."}` JSON to stdout.
PRD US 18: input violations as argparse error (exit 2).

Either reject at parse time (exit 2) or emit JSON error (exit 1). Never traceback.

## Proposed fix direction

Validate `--limit >= 1` at argparse `type=`, or guard the `skip // limit`
page calculation in `get_transactions_with_pagination`.
