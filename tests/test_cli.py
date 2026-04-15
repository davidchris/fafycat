"""CLI entry point tests invoked via subprocess.

These tests exercise the real entry point — either the pre-refactor
``cli.py`` at repo root or the post-refactor ``fafycat.cli`` module. The
``cli_runner`` fixture in conftest autodetects which one to invoke, so
these assertions hold on both sides of the packaging refactor.
"""

import json
from pathlib import Path

import pytest
from fafycat import cli


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


def test_cli_import_malformed_csv_prints_error_json(cli_runner, tmp_path):
    """A CSV whose columns don't match the expected schema exits non-zero
    with a structured error payload — never a bare traceback."""
    csv = tmp_path / "bad.csv"
    csv.write_text("foo,bar,baz\n1,2,3\n")

    result = cli_runner("import", str(csv))
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert "error" in payload


def test_legacy_database_url_uses_legacy_prod_db_in_prod(tmp_path, monkeypatch):
    legacy_db = tmp_path / "data" / "fafycat_prod.db"
    legacy_db.parent.mkdir()
    legacy_db.write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FAFYCAT_DB_URL", raising=False)

    assert cli._legacy_database_url(data_dir=None, dev=False) == f"sqlite:///{legacy_db.resolve()}"


def test_legacy_database_url_skips_dev_mode(tmp_path, monkeypatch):
    legacy_db = tmp_path / "data" / "fafycat_prod.db"
    legacy_db.parent.mkdir()
    legacy_db.write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FAFYCAT_DB_URL", raising=False)

    assert cli._legacy_database_url(data_dir=None, dev=True) is None


def test_legacy_database_url_skips_explicit_data_dir(tmp_path, monkeypatch):
    legacy_db = tmp_path / "data" / "fafycat_prod.db"
    legacy_db.parent.mkdir()
    legacy_db.write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FAFYCAT_DB_URL", raising=False)

    assert cli._legacy_database_url(data_dir=Path("/tmp/custom-data"), dev=False) is None


@pytest.mark.integration
def test_cli_import_valid_csv_prints_expected_json_shape(cli_runner, tmp_path):
    """The CLI's public JSON contract: these four keys must be present.

    Any breakage of this shape is a user-visible regression, so the
    assertion is part of the refactor's green-light set.

    Marked ``integration`` because it exercises CSV parsing, DB writes,
    and ML prediction in a single subprocess.
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
