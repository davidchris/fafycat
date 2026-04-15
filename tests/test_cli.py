"""CLI entry point tests invoked via subprocess.

These tests exercise the real entry point — either the pre-refactor
``cli.py`` at repo root or the post-refactor ``fafycat.cli`` module. The
``cli_runner`` fixture in conftest autodetects which one to invoke, so
these assertions hold on both sides of the packaging refactor.
"""

import json


def test_cli_help_exits_zero(cli_runner):
    result = cli_runner("--help")
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert "usage" in result.stdout.lower() or "fafycat" in result.stdout.lower()


def test_cli_import_help_exits_zero(cli_runner):
    result = cli_runner("import", "--help")
    assert result.returncode == 0, f"stderr={result.stderr!r}"


def test_cli_import_nonexistent_file_prints_error_json(cli_runner):
    result = cli_runner("import", "/nonexistent/path/to.csv")
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert "error" in payload
    assert "not found" in payload["error"].lower()


def test_cli_import_valid_csv_prints_expected_json_shape(cli_runner, tmp_path):
    """The CLI's public JSON contract: these four keys must be present.

    Any breakage of this shape is a user-visible regression, so the
    assertion is part of the refactor's green-light set.
    """
    csv = tmp_path / "sample.csv"
    csv.write_text("date,name,purpose,amount,currency\n2025-01-01,Test Store,Purchase,-10.00,EUR\n")

    result = cli_runner("import", str(csv))
    assert result.returncode == 0, f"stderr={result.stderr!r}"

    payload = json.loads(result.stdout)
    assert payload["filename"] == "sample.csv"
    assert payload["rows_processed"] == 1
    assert "transactions_imported" in payload
    assert "duplicates_skipped" in payload
