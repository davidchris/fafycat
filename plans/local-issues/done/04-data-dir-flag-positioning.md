# [CLI] --data-dir only works at group level, not on subcommand or root

**Severity:** blocker
**Source:** QA of issue #26 (`plans/qa-issue-26-findings.md` finding 4)

## Repro

```bash
uv run fafycat tx list --data-dir $QA_DIR --limit 1   # FAILS
uv run fafycat --data-dir $QA_DIR tx list --limit 1   # FAILS
uv run fafycat tx --data-dir $QA_DIR list --limit 1   # works
```

## Observed

```
fafycat: error: unrecognized arguments: --data-dir /var/.../fafycat-qa-...
fafycat: error: argument command: invalid choice: '/var/.../fafycat-qa-...'
```

Flag only parses between group (`tx`/`cat`/`budget`/`analytics`) and
subcommand (`list`/`show`/etc). Two of three natural positions fail.

`skill` group has no `--data-dir` flag at all (acceptable since
`skill install` does not touch the DB, but worth confirming intent).

## Expected

PRD US 21: `--data-dir` flag overrides DB location.
PRD US 28: flag/config affect every subcommand.

Most users (and any agent reading SKILL.md) will type
`fafycat tx list --data-dir ...` first. Current parser corners them
onto a non-obvious single position with no hint.

## Proposed fix direction

Add `--data-dir` as root-level argument so all positions parse, or
replicate on every leaf subparser. Update SKILL.md with one working
example showing positioning.
