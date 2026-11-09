## Development setup

- Python 3.13+ required
- `uv` is the package manager
- **Run app**: `uv run fafycat serve --dev`
- **Run app (prod)**: `uv run fafycat serve`
- **Init data**: `uv run fafycat init`
- **Import CSV**: `uv run fafycat import path/to/file.csv`
- **Custom data dir**: `uv run fafycat serve --data-dir /path/to/data`
- **Lint**: `ruff check` (configured for line length 120, Python 3.13+)
- **Format**: `ruff format`
- **Type Check**: `ty check`. Most rules are set to `warn` in `pyproject.toml`, so existing
  warnings do not fail the check; do not add new ones. `scripts/` and `simulations/` are
  type-checked with `unresolved-import` ignored: they may import optional deps (optuna,
  mlx_lm, ...) that are not in the default `.venv`. `pyproject.toml` defines only the
  `dev` dependency group, so install such a dep ad hoc with `uv pip install <dep>` before running
  the script (do not use `uv sync --group <name>`, no such group exists).
- **Run Tests**: `uv run pytest` (Python, in `tests/`) and `node --test tests_js/*.test.js` (JavaScript)
- **Verify (all checks, same as CI)**: `just verify`. Run it before you report a change as done: it runs
  `ruff format --check`, `ruff check`, `ty check`, `uv run pytest`, and the JavaScript tests.
- **Test Coverage**: Python tests go in `tests/`, JavaScript tests in `tests_js/`
- Verify UI behaviour in a real browser with Playwright. There is no browser test suite yet;
  `scripts/capture_readme_demo.sh` shows how to install Playwright and drive an isolated dev server.
- Dependencies managed via `pyproject.toml`
- Use `uv add <dependency>` to add new dependencies
- use `git`, not `git -C`

## Project structure

All application code lives under `src/fafycat/`:
- `src/fafycat/app.py` — FastAPI application factory (`create_app()`)
- `src/fafycat/cli.py` — Unified CLI entry point
- `src/fafycat/api/` — API routes and services
- `src/fafycat/web/` — FastHTML web pages and components
- `src/fafycat/core/` — Config, database, models
- `src/fafycat/data/` — CSV processing
- `src/fafycat/ml/` — ML pipeline
- `src/fafycat/static/` — CSS, JS, favicon

Read `GLOSSARY.md` (the domain terms) before you change domain behaviour. Read the ADRs in `docs/adr/` too, if that directory exists.

User data defaults to the platform user data directory. Override it with `--data-dir` or `FAFYCAT_DATA_DIR`.

## Coding Style

- Follow Google Python Style Guide, and docstring style
- After implementing a change, run linter and tests, fix any upcoming issues
- Always test end-to-end functionality with the dev db
- Boy Scout Rule: leave code better than you found it
- Is it about finding FILES? use 'fd'
- Is it about finding TEXT/strings? use 'rg'
- Is it about finding CODE STRUCTURE? use 'ast-grep'
- Is it about SELECTING from multiple results? pipe to 'fzf'
- Is it about interacting with JSON? use 'jq'
- Is it about interacting with YAML or XML? use 'yq'

## Agent skills

### Issue tracker

GitHub Issues on `davidchris/fafycat`, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Workflow

Definition of Ready and Done, evidence rules, filing rule, and merge gate. See `docs/agents/workflow.md`.
