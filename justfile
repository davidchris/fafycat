# Run every check that proves a change: format, lint, typecheck, tests.
verify:
    uv run ruff format --check
    uv run ruff check
    uv run ty check
    uv run pytest
    node --test tests_js/*.test.js
