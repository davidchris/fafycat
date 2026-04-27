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


@pytest.mark.integration
def test_cat_list_empty_db_returns_empty_list(cli_runner):
    """cat list on a fresh DB returns an empty JSON array, not an error."""
    result = cli_runner("cat", "list")
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    payload = json.loads(result.stdout)
    assert payload == []


@pytest.mark.integration
def test_cat_list_after_init_returns_categories_with_required_keys(cli_runner):
    """After init, cat list returns categories each with id, name, type, is_active, budget."""
    cli_runner("init")
    result = cli_runner("cat", "list")
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert len(payload) > 0
    cat = payload[0]
    for key in ("id", "name", "type", "is_active", "budget"):
        assert key in cat, f"missing key {key!r}"


@pytest.mark.integration
def test_cat_list_include_inactive_returns_all(cli_runner):
    """--include-inactive flag returns categories regardless of active status."""
    cli_runner("init")
    result_active = cli_runner("cat", "list")
    result_all = cli_runner("cat", "list", "--include-inactive")
    assert result_active.returncode == 0
    assert result_all.returncode == 0
    active_count = len(json.loads(result_active.stdout))
    all_count = len(json.loads(result_all.stdout))
    assert all_count >= active_count


@pytest.mark.integration
def test_budget_show_after_init_returns_expected_shape(cli_runner):
    """budget show <year> returns JSON with year, budgets list, and total_categories."""
    cli_runner("init")
    result = cli_runner("budget", "show", "2025")
    assert result.returncode == 0, f"stderr={result.stderr!r}\nstdout={result.stdout!r}"
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    for key in ("year", "budgets", "total_categories"):
        assert key in payload, f"missing key {key!r}"
    assert payload["year"] == 2025
    assert isinstance(payload["budgets"], list)


@pytest.mark.integration
def test_analytics_monthly_returns_json_shape(cli_runner):
    """analytics monthly --year 2025 returns JSON with year, monthly_data, and yearly_totals."""
    cli_runner("init")
    result = cli_runner("analytics", "monthly", "--year", "2025")
    assert result.returncode == 0, f"stderr={result.stderr!r}\nstdout={result.stdout!r}"
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    for key in ("year", "monthly_data", "yearly_totals"):
        assert key in payload, f"missing key {key!r}"
    assert payload["year"] == 2025
    assert isinstance(payload["monthly_data"], list)
    assert len(payload["monthly_data"]) == 12


@pytest.mark.integration
def test_analytics_breakdown_returns_json_shape(cli_runner):
    """analytics breakdown --year 2025 returns JSON with categories, summary, and date_range."""
    cli_runner("init")
    result = cli_runner("analytics", "breakdown", "--year", "2025")
    assert result.returncode == 0, f"stderr={result.stderr!r}\nstdout={result.stdout!r}"
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    for key in ("categories", "summary", "date_range"):
        assert key in payload, f"missing key {key!r}"
    assert isinstance(payload["categories"], list)
    assert isinstance(payload["summary"], dict)
    for key in ("total_amount", "total_categories"):
        assert key in payload["summary"], f"missing summary key {key!r}"


@pytest.mark.integration
def test_tx_list_empty_db_returns_pagination_envelope(cli_runner):
    """tx list on a fresh DB returns a pagination envelope with an empty transactions list."""
    cli_runner("init")
    result = cli_runner("tx", "list")
    assert result.returncode == 0, f"stderr={result.stderr!r}\nstdout={result.stdout!r}"
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    for key in ("transactions", "total_count", "has_next", "skip", "limit"):
        assert key in payload, f"missing key {key!r}"
    assert isinstance(payload["transactions"], list)
    assert payload["total_count"] == 0
    assert payload["skip"] == 0
    assert payload["limit"] == 20
