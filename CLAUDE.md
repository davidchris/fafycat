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
- **Type Check**: `ty check` (strict typing enabled)
- **Run Tests**: `uv run pytest`
- **Test Coverage**: Tests should be in `tests/` directory
- use puppeteer to verify UI functionality
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
