# [test] cat list --include-inactive coverage gap

**Severity:** nit
**Source:** QA of issue #26 (`plans/qa-issue-26-findings.md` finding 15)

## Repro

```bash
uv run fafycat cat --data-dir $QA_DIR list                     # 17 rows
uv run fafycat cat --data-dir $QA_DIR list --include-inactive  # 17 rows
```

## Observed

Default and `--include-inactive` return identical counts. No inactive
categories exist in default-seeded set, so flag has nothing to expose.
PRD US 9 contract technically met but coverage shallow — could not
prove flag actually works.

## Expected

PRD US 9: `fafycat cat list` returns all categories with budgets and
types; `--include-inactive` switches between active-only (default) and
all.

## Proposed fix direction

Add test fixture that toggles a category inactive and asserts default
omits it while `--include-inactive` includes it. Pure test addition,
no production code change unless the test exposes a bug.
