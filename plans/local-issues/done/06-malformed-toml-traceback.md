# [CLI] malformed TOML in FAFYCAT_CONFIG surfaces tomllib traceback

**Severity:** blocker
**Source:** QA of issue #26 (`plans/qa-issue-26-findings.md` finding 6)

## Repro

```bash
echo '[unclosed' > /tmp/bad.toml
FAFYCAT_CONFIG=/tmp/bad.toml FAFYCAT_DATA_DIR=$QA_DIR uv run fafycat tx list --limit 1
```

## Observed

```
File "src/fafycat/core/config_file.py", line 37, in load_config_file
    data = tomllib.load(f)
...
raise suffixed_err(src, pos, "Expected ']' at the end of a table declaration")
```

Raw `tomllib.TOMLDecodeError` traceback. Breaks JSON-pure stdout
contract.

## Expected

PRD US 26: malformed TOML / invalid path syntax → fail loudly with
clear error.
PRD US 17: errors as `{"error": "..."}` JSON to stdout, exit 1.

Loud yes, clear no — traceback fails the "clear" half and the JSON
contract.

## Proposed fix direction

Wrap `tomllib.load` in `src/fafycat/core/config_file.py`, catch
`tomllib.TOMLDecodeError`, raise project-level error type whose
message names the file path. Emit via existing `{"error": ...}`
framing.
