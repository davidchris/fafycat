# Using FafyCat with a coding agent

FafyCat ships a small read-only CLI surface designed for use by coding agents like Claude Code, Cursor, or any tool that can shell out and read JSON. This guide shows how to wire it up and what the agent can do.

The CLI never mutates your data. It only reads from your existing FafyCat database. Imports and re-categorization still happen through `fafycat import` and the web UI.

## Why a separate CLI for agents?

The web UI is built for humans. Agents need:

- **Stable, machine-parseable output.** Every read-only command prints JSON to stdout (`indent=2`, exit 0) or `{"error": "..."}` (exit 1). No prose, no spinners, no ANSI.
- **Predictable flags.** Date filters, pagination, and category filters all share the same shape across commands.
- **No browser.** Works inside any agent loop without launching the FastAPI server.

If you only ever want to ask "what did I spend on groceries last month?" from inside an editor, this is enough. You do not need to keep `fafycat serve` running.

## One-time setup

1. Make sure FafyCat is installed and you have at least one CSV imported. See the main [README](../README.md) for the install path.
2. Verify the CLI sees your data:
   ```bash
   fafycat cat list
   ```
   You should get a JSON envelope with your categories.

If you keep your FafyCat database somewhere non-default, point the CLI at it with one of:

- `--data-dir /path/to/data` flag (accepted at any position: root, group, or leaf)
- `FAFYCAT_DATA_DIR` env var
- `~/.config/fafycat/config.toml` with `[paths] data_dir = "..."`

Precedence: flag > env var > config file > platform default.

## Plugging into Claude Code

FafyCat bundles a Claude Code skill that documents every command, its flags, and its response shape. Install it into your project:

```bash
fafycat skill install
```

This writes `./.claude/skills/fafycat/SKILL.md`. Claude Code auto-discovers skills in `.claude/skills/` and loads the file when you ask a finance-related question. You can also install it elsewhere:

```bash
fafycat skill install ~/myproject/.claude/skills/fafycat
fafycat skill install --force   # overwrite an existing copy
```

For other agents, point them at the same `SKILL.md` — it is plain Markdown describing the CLI contract and is reusable as a system prompt or tool description.

## What the agent can do

All commands return JSON. The full reference lives in the bundled `SKILL.md`; this is a short tour.

### Inspect categories and budgets

```bash
fafycat cat list
fafycat cat list --include-inactive
fafycat budget show 2025
```

`budget show` returns `has_year_specific_budgets: false` when every entry is a fallback (the year was never explicitly budgeted). Treat that the same as "year not budgeted".

### Query transactions

```bash
fafycat tx list --month 2025-01
fafycat tx list --ytd --category Groceries --limit 50
fafycat tx list --unreviewed --last-n-months 3
```

Pagination: `--skip`, `--limit` (default 20, cap 500). Response envelope includes `total_count` and `has_next`.

### Analytics

```bash
fafycat analytics monthly --year 2025
fafycat analytics breakdown --ytd --type spending
fafycat analytics variance --year 2025
fafycat analytics savings --year 2025
fafycat analytics yoy --type spending --years 2023,2024,2025
fafycat analytics top --year 2025 --month 3
```

`--type` on `breakdown` accepts exactly `income`, `saving`, or `spending` — anything else exits with code 2.

### Date flags (shared across commands)

All mutually exclusive with each other and with `--start`/`--end`:

- `--month YYYY-MM`
- `--year YYYY`
- `--this-month`
- `--last-month`
- `--ytd`
- `--last-n-months N`

## Working patterns

A few prompts that work well:

- *"How does my YTD spending compare to budget?"* — agent runs `fafycat analytics variance --ytd` and summarises.
- *"What were my five biggest expenses last month?"* — agent runs `fafycat analytics top --last-month`.
- *"Find any unreviewed transactions over 100 EUR in the last 3 months."* — agent runs `fafycat tx list --unreviewed --last-n-months 3 --limit 500` and filters client-side.
- *"Build me a year-end summary notebook."* — agent runs `analytics monthly`, `breakdown`, `savings`, and stitches the JSON into a notebook or report.

## Boundaries

- **Read only.** There is no `tx update`, `tx delete`, `cat create`, etc. on the CLI. Agents cannot change your data through this surface. To re-categorize, send the agent to the review UI.
- **Local only.** No network calls. Your data does not leave the machine the CLI runs on.
- **No row-level personal data in shared output.** When asking the agent to write a public artefact (issue, PR, gist), tell it to keep amounts and category names generic.

## Troubleshooting

- **`{"error": "..."}` and exit 1.** Almost always a bad date flag combination, an unknown category name, or a missing database. Run `fafycat init` if the database is missing.
- **Exit code 2.** Argparse rejected the input (e.g. `--type` outside the allowed set, `--month` not in `YYYY-MM`).
- **Empty results from a freshly installed FafyCat.** Run `fafycat import path/to/file.csv` first or boot `fafycat serve --dev` to seed synthetic data.
- **Skill not picked up.** Confirm the file lives at `.claude/skills/fafycat/SKILL.md` relative to the directory you opened in Claude Code. Re-run `fafycat skill install --force` if you suspect drift.
