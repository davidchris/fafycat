# [CLI] argparse vs JSON error split is inconsistent across input validators

**Severity:** friction
**Source:** QA of issue #26 (`plans/qa-issue-26-findings.md` finding 7)

## Repro

```bash
uv run fafycat tx --data-dir $QA_DIR list --year abc                          # exit 2, argparse usage to stderr
uv run fafycat tx --data-dir $QA_DIR list --month foo                         # exit 1, JSON {"error": ...}
uv run fafycat tx --data-dir $QA_DIR list --month 2026-13                     # exit 1, JSON {"error": ...}
uv run fafycat tx --data-dir $QA_DIR list --start 2025-99-99                  # exit 2, argparse usage
uv run fafycat tx --data-dir $QA_DIR list --month 2026-01 --start 2026-01-01  # exit 1, JSON
uv run fafycat tx --data-dir $QA_DIR list --start 2026-12-01 --end 2025-01-01 # exit 1, JSON
uv run fafycat tx --data-dir $QA_DIR list --last-n-months 0                   # exit 1, JSON
```

## Observed

Mixed exit codes. Whether `--month foo` is exit 1 vs `--year abc` is
exit 2 looks like coincidence of which validator ran first. Same for
mutual exclusion: `--reviewed --unreviewed` is argparse (exit 2) but
date-sugar vs `--start`/`--end` is runtime (exit 1).

## Expected

PRD US 8 (mutual exclusion), 17 (runtime JSON), 18 (argparse exit 2).
Pick one rule and apply consistently.

Agent that hardcodes one parse path per the PRD will hit both shapes
and need conditional handling.

## Proposed fix direction

Decide one rule: e.g. "anything argparse can catch (format,
mutual-exclusion) lives in `type=` / mutually-exclusive groups; the
rest is JSON exit 1". Apply across `tx list` and analytics. Document.
