## Development setup

- Python 3.13+ required
- `uv` is the package manager
- run python commands with `uv run python ...`
- **Lint**: `ruff check` (configured for line length 120, Python 3.13+)
- **Format**: `ruff format`
- **Type Check**: `ty check` (strict typing enabled)
- **Run Tests**: `uv run pytest` (when implemented)
- **Test Coverage**: Tests should be in `tests/` directory
- use puppeteer to verify UI functionality
- Dependencies managed via `pyproject.toml`
- Use `uv pip install -e .` for editable install
- Use `uv add <dependency>` to add new dependencies

## Coding Style

- Follow Google Python Style Guide, and docstring style
- After implementing a change, run linter and tests, fix any upcoming issues
- Always test end-to-end functionality with the dev db
- Is it about finding FILES? use 'fd'
- Is it about finding TEXT/strings? use 'rg'
- Is it about finding CODE STRUCTURE? use 'ast-grep'
- Is it about SELECTING from multiple results? pipe to 'fzf'
- Is it about interacting with JSON? use 'jq'
- Is it about interacting with YAML or XML? use 'yq'
