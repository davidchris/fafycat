# [CLI] config-file loader runs 3× per invocation, warnings duplicated

**Severity:** friction
**Source:** QA of issue #26 (`plans/qa-issue-26-findings.md` finding 10)

## Repro

```bash
cat > $QA_DIR/cfg.toml <<EOF
[paths]
data_dir = "/wrong"
unknown_key = "x"
EOF
FAFYCAT_CONFIG=$QA_DIR/cfg.toml FAFYCAT_DATA_DIR=$QA_DIR \
  uv run fafycat tx --data-dir $QA_DIR list --limit 1
```

## Observed

stderr contains the same warning three times:
```
Warning: unknown key 'unknown_key' in [.../cfg.toml] [paths]
Warning: unknown key 'unknown_key' in [.../cfg.toml] [paths]
Warning: unknown key 'unknown_key' in [.../cfg.toml] [paths]
```

## Expected

PRD US 25: one stderr warning per unknown key. User shouldn't be able
to tell loader runs more than once.

Three warnings = loader called three times = config file parsed three
times per invocation.

## Proposed fix direction

Memoize `load_config_file` (e.g. `@functools.cache`), or hoist
resolution into single `AppConfig` construction so each `_default_*`
factory shares the cached result.
