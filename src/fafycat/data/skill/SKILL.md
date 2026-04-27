---
description: Query household finance data via the fafycat CLI (transactions, categories, budgets, analytics). All output is JSON.
---

# FafyCat CLI reference

Read-only access to your household finance data. Every command prints JSON to stdout (indent=2, exit 0) or `{"error":"..."}` (exit 1).

## Commands

### `fafycat tx list`
Paginated transaction list. Response envelope: `transactions`, `total_count`, `has_next`, `skip`, `limit`. Default limit 20, cap 500.
```
fafycat tx list --month 2025-01
fafycat tx list --ytd --category Groceries --limit 50
```

### `fafycat cat list`
Response envelope: `categories` (list of `{id, name, type, is_active, budget, created_at, updated_at}`), `total_count`.
```
fafycat cat list
fafycat cat list --include-inactive
```

### `fafycat budget show <year>`
Per-category budgets for a year. Response: `year`, `budgets`, `total_categories`, `has_year_specific_budgets`.
`has_year_specific_budgets` is `true` only when at least one category has an explicit budget plan for that year;
`false` means all entries are fallback (category default) budgets — treat this the same as "year not budgeted".
Each `budgets` entry: `category_id`, `category_name`, `category_type`, `monthly_budget`, `has_year_specific`, `fallback_budget`.
```
fafycat budget show 2025
```

### `fafycat analytics monthly`
Monthly income/spending/saving totals. Response: `year`, `monthly_data` (12 entries), `yearly_totals`.
```
fafycat analytics monthly --year 2025
fafycat analytics monthly --ytd
```

### `fafycat analytics breakdown`
Per-category spending totals for a date range. Response: `categories`, `summary`, `date_range`.
`--type` accepts exactly: `income`, `saving`, `spending` (invalid values exit 2).
```
fafycat analytics breakdown --year 2025
fafycat analytics breakdown --ytd --type spending
```

### `fafycat analytics variance`
Budget-vs-actual variance per category. Response: `variances`, `summary`, `date_range`.
```
fafycat analytics variance --year 2025
fafycat analytics variance --ytd
```

### `fafycat analytics savings`
Monthly and cumulative savings. Response: `year`, `monthly_savings`, `statistics`.
```
fafycat analytics savings --year 2025
```

### `fafycat analytics yoy`
Year-over-year comparison by category. Response: `categories`, `summary` (includes `years`).
```
fafycat analytics yoy
fafycat analytics yoy --type spending --years 2023,2024,2025
```

### `fafycat analytics top`
Largest spending transactions for a month. `--year` defaults to current year; `--month` defaults to current month.
Response: `year`, `month`, `month_name`, `top_transactions`, `total_spending`, `transactions_count`.
```
fafycat analytics top --year 2025 --month 3
fafycat analytics top --limit 10
```

## Date flags (mutually exclusive with each other and with `--start`/`--end`)

- `--month YYYY-MM` — calendar month
- `--year YYYY` — full calendar year
- `--this-month` — current month
- `--last-month` — previous month
- `--ytd` — year-to-date
- `--last-n-months N` — rolling N-month window

## Database override

- `--data-dir PATH` flag, or `FAFYCAT_DATA_DIR` env var, or `~/.config/fafycat/config.toml` `[paths] data_dir`
- Precedence: flag > env var > config file > platform default
- The flag is accepted at any position — root, group, or leaf:
  ```
  fafycat tx list --data-dir /path/to/data
  fafycat --data-dir /path/to/data tx list
  fafycat tx --data-dir /path/to/data list
  ```
