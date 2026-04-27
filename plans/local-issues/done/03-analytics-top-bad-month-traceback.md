# [CLI] analytics top --month >12 throws ValueError instead of JSON error

**Severity:** blocker
**Source:** QA of issue #26 (`plans/qa-issue-26-findings.md` finding 3)

## Repro

```bash
uv run fafycat analytics --data-dir $QA_DIR top --year 2025 --month 13
```

## Observed

```
File "src/fafycat/api/services.py", line 920, in get_top_transactions_by_month
    "month_name": date(year, month, 1).strftime("%B"),
ValueError: month must be in 1..12
exit=1
```

`datetime.date` raises before service can return clean envelope.

## Expected

PRD US 16: `analytics top` returns largest spending transactions for given month.
PRD US 17: out-of-range input → JSON error envelope.
PRD US 18: invalid input could also be argparse-validated → exit 2.

## Proposed fix direction

Validate `1 <= month <= 12` in handler before calling service, or use
argparse `choices=range(1, 13)` (or custom `type=`) on `--month`.
