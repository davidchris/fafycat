# [CLI] analytics yoy --years rejects bad value with traceback

**Severity:** blocker
**Source:** QA of issue #26 (`plans/qa-issue-26-findings.md` finding 2)

## Repro

```bash
FAFYCAT_DATA_DIR=$QA_DIR uv run fafycat analytics yoy --years foo
```

## Observed

```
File "src/fafycat/cli.py", line 460, in cmd_analytics_yoy
    years = [int(y.strip()) for y in args.years.split(",")]
ValueError: invalid literal for int() with base 10: 'foo'
exit=1
```

Uncaught `ValueError`. No JSON error envelope.

## Expected

PRD US 17: malformed input → `{"error": "..."}` JSON, exit 1.
PRD US 18: parse-time validation → argparse error, exit 2.

Agent gets parseable signal, no traceback.

## Proposed fix direction

Custom argparse `type=` that splits the comma list and validates each
entry as `int`. Or wrap the parse in try/except in `cmd_analytics_yoy`
and emit `{"error": ...}`.
