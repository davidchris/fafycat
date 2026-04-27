"""CLI entry point tests invoked via subprocess.

These tests exercise the real entry point — either the pre-refactor
``cli.py`` at repo root or the post-refactor ``fafycat.cli`` module. The
``cli_runner`` fixture in conftest autodetects which one to invoke, so
these assertions hold on both sides of the packaging refactor.
"""

import json
import sqlite3
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
def test_cat_list_returns_envelope_shape(cli_runner):
    """cat list on a fresh DB returns envelope with categories list and total_count."""
    result = cli_runner("cat", "list")
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict), "expected envelope dict, got bare array or other type"
    assert "categories" in payload
    assert "total_count" in payload
    assert payload["categories"] == []
    assert payload["total_count"] == 0


@pytest.mark.integration
def test_cat_list_after_init_returns_categories_with_required_keys(cli_runner):
    """After init, cat list returns envelope with categories each having required keys."""
    cli_runner("init")
    result = cli_runner("cat", "list")
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    assert "categories" in payload and "total_count" in payload
    assert len(payload["categories"]) > 0
    cat = payload["categories"][0]
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
    active_count = json.loads(result_active.stdout)["total_count"]
    all_count = json.loads(result_all.stdout)["total_count"]
    assert all_count >= active_count


@pytest.mark.integration
def test_cat_list_include_inactive_actually_filters(cli_runner, tmp_data_dir: Path):
    """--include-inactive exposes categories toggled inactive; default omits them."""
    cli_runner("init")
    db_path = tmp_data_dir / "test.db"
    with sqlite3.connect(str(db_path)) as conn:
        (inactive_name,) = conn.execute(
            "SELECT name FROM categories WHERE is_active = 1 ORDER BY id LIMIT 1"
        ).fetchone()
        conn.execute("UPDATE categories SET is_active = 0 WHERE name = ?", (inactive_name,))
    result_active = cli_runner("cat", "list")
    result_all = cli_runner("cat", "list", "--include-inactive")
    assert result_active.returncode == 0, f"stderr={result_active.stderr!r}"
    assert result_all.returncode == 0, f"stderr={result_all.stderr!r}"
    payload_active = json.loads(result_active.stdout)
    payload_all = json.loads(result_all.stdout)
    assert payload_all["total_count"] == payload_active["total_count"] + 1
    active_names = {c["name"] for c in payload_active["categories"]}
    all_names = {c["name"] for c in payload_all["categories"]}
    assert inactive_name not in active_names
    assert inactive_name in all_names


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
def test_budget_show_no_year_specific_budgets_flag(cli_runner):
    """budget show for a year with no explicit budgets sets has_year_specific_budgets=False."""
    cli_runner("init")
    result = cli_runner("budget", "show", "9999")
    assert result.returncode == 0, f"stderr={result.stderr!r}\nstdout={result.stdout!r}"
    payload = json.loads(result.stdout)
    assert "has_year_specific_budgets" in payload, "missing has_year_specific_budgets key"
    assert payload["has_year_specific_budgets"] is False


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
def test_analytics_variance_year(cli_runner):
    """analytics variance --year 2025 returns JSON with variances, summary, and date_range."""
    cli_runner("init")
    result = cli_runner("analytics", "variance", "--year", "2025")
    assert result.returncode == 0, f"stderr={result.stderr!r}\nstdout={result.stdout!r}"
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    for key in ("variances", "summary", "date_range"):
        assert key in payload, f"missing key {key!r}"
    assert isinstance(payload["variances"], list)
    assert isinstance(payload["summary"], dict)


@pytest.mark.integration
def test_analytics_savings_returns_json_shape(cli_runner):
    """analytics savings --year 2025 returns JSON with year, monthly_savings, and statistics."""
    cli_runner("init")
    result = cli_runner("analytics", "savings", "--year", "2025")
    assert result.returncode == 0, f"stderr={result.stderr!r}\nstdout={result.stdout!r}"
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    for key in ("year", "monthly_savings", "statistics"):
        assert key in payload, f"missing key {key!r}"
    assert payload["year"] == 2025
    assert isinstance(payload["monthly_savings"], list)
    assert isinstance(payload["statistics"], dict)


@pytest.mark.integration
def test_analytics_yoy_returns_json_shape(cli_runner):
    """analytics yoy returns JSON with categories list and summary with years key."""
    cli_runner("init")
    result = cli_runner("analytics", "yoy")
    assert result.returncode == 0, f"stderr={result.stderr!r}\nstdout={result.stdout!r}"
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    for key in ("categories", "summary"):
        assert key in payload, f"missing key {key!r}"
    assert isinstance(payload["categories"], list)
    assert isinstance(payload["summary"], dict)
    assert "years" in payload["summary"]


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


def test_tx_list_limit_zero_exits_with_argparse_error(cli_runner):
    """--limit 0 must be rejected at parse time (exit 2), not traceback."""
    result = cli_runner("tx", "list", "--limit", "0")
    assert result.returncode == 2, (
        f"expected exit 2, got {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


def test_tx_list_negative_limit_exits_with_argparse_error(cli_runner):
    """--limit -1 must be rejected at parse time (exit 2), not silently dump all rows."""
    result = cli_runner("tx", "list", "--limit", "-1")
    assert result.returncode == 2, (
        f"expected exit 2, got {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


def test_analytics_yoy_bad_years_exits_with_argparse_error(cli_runner):
    """--years foo must be rejected at parse time (exit 2), not traceback."""
    result = cli_runner("analytics", "yoy", "--years", "foo")
    assert result.returncode == 2, (
        f"expected exit 2, got {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


def test_analytics_top_bad_month_exits_with_argparse_error(cli_runner):
    """--month 13 must be rejected at parse time (exit 2), not ValueError traceback."""
    result = cli_runner("analytics", "top", "--year", "2025", "--month", "13")
    assert result.returncode == 2, (
        f"expected exit 2, got {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


def test_analytics_top_returns_json_shape(cli_runner):
    """analytics top returns JSON with year, month, top_transactions, total_spending, transactions_count."""
    cli_runner("init")
    result = cli_runner("analytics", "top", "--year", "2025", "--month", "1")
    assert result.returncode == 0, f"stderr={result.stderr!r}\nstdout={result.stdout!r}"
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    for key in ("year", "month", "month_name", "top_transactions", "total_spending", "transactions_count"):
        assert key in payload, f"missing key {key!r}"
    assert isinstance(payload["top_transactions"], list)
    assert payload["year"] == 2025
    assert payload["month"] == 1


def test_data_dir_recognized_at_leaf_position(cli_runner, tmp_path):
    """--data-dir must parse when placed after the leaf subcommand (PRD US 21, US 28).

    `fafycat tx list --data-dir PATH` was rejecting with exit 2 ("unrecognized arguments")
    because --data-dir was only registered on the group parser, not the leaf subparser.
    """
    result = cli_runner("tx", "list", "--data-dir", str(tmp_path))
    assert result.returncode != 2, (
        f"--data-dir not recognized at leaf position (exit 2 = argparse 'unrecognized arguments')\n"
        f"stderr={result.stderr!r}"
    )


def test_malformed_config_toml_returns_json_error(cli_runner, tmp_path, monkeypatch):
    """FAFYCAT_CONFIG pointing to malformed TOML must exit 1 with JSON error (US 17), not a traceback."""
    bad_toml = tmp_path / "bad.toml"
    bad_toml.write_text("[unclosed\n")
    monkeypatch.setenv("FAFYCAT_CONFIG", str(bad_toml))
    result = cli_runner("tx", "list")
    assert result.returncode == 1, f"stderr={result.stderr!r}\nstdout={result.stdout!r}"
    payload = json.loads(result.stdout)
    assert "error" in payload
    assert "Malformed TOML" in payload["error"]


@pytest.mark.integration
def test_skill_install_writes_skill_md(cli_runner, tmp_path):
    """skill install writes SKILL.md to target dir; file has frontmatter description and mentions fafycat."""
    target = tmp_path / "skills" / "fafycat"
    result = cli_runner("skill", "install", str(target))
    assert result.returncode == 0, f"stderr={result.stderr!r}\nstdout={result.stdout!r}"
    skill_file = target / "SKILL.md"
    assert skill_file.exists(), "SKILL.md was not written"
    content = skill_file.read_text()
    assert "description:" in content, "frontmatter missing 'description' key"
    assert "fafycat" in content.lower(), "skill body does not mention fafycat"


def test_skill_md_cat_list_includes_timestamp_fields():
    """SKILL.md cat list section must document created_at and updated_at (issue 12b)."""
    import importlib.resources

    content = importlib.resources.files("fafycat.data.skill").joinpath("SKILL.md").read_text(encoding="utf-8")
    assert "created_at" in content, "SKILL.md cat list missing created_at field"
    assert "updated_at" in content, "SKILL.md cat list missing updated_at field"


def test_skill_md_analytics_top_documents_defaults():
    """SKILL.md analytics top section must document current-year/current-month defaults (issue 12c)."""
    import importlib.resources

    content = importlib.resources.files("fafycat.data.skill").joinpath("SKILL.md").read_text(encoding="utf-8")
    assert "current year" in content, "SKILL.md analytics top missing 'current year' default documentation"
    assert "current month" in content, "SKILL.md analytics top missing 'current month' default documentation"


def test_tx_list_month_bad_format_exits_with_argparse_error(cli_runner):
    """--month foo must be rejected at parse time (exit 2, US 18), not JSON exit 1."""
    result = cli_runner("tx", "list", "--month", "foo")
    assert result.returncode == 2, (
        f"expected exit 2, got {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


def test_analytics_breakdown_invalid_type_exits_with_argparse_error(cli_runner):
    """--type bogus must be rejected at parse time (exit 2), not silently return empty results."""
    result = cli_runner("analytics", "breakdown", "--type", "bogus")
    assert result.returncode == 2, (
        f"expected exit 2, got {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
