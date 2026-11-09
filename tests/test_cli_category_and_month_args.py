"""CLI: `analytics top --last-month`, and `--category` that ignores case and rejects unknown names."""

import json
from datetime import date

import pytest
from dateutil.relativedelta import relativedelta

from fafycat.core.config import AppConfig
from fafycat.core.database import CategoryORM, DatabaseManager, TransactionORM

LAST_MONTH = date.today().replace(day=1) - relativedelta(months=1)


@pytest.fixture
def seeded(cli_runner, tmp_data_dir, monkeypatch):
    """An initialised database with one groceries expense last month."""
    monkeypatch.setenv("FAFYCAT_CONFIG", str(tmp_data_dir / "no-such-config.toml"))
    assert cli_runner("init").returncode == 0
    manager = DatabaseManager(AppConfig())
    with manager.get_session() as session:
        groceries = session.query(CategoryORM).filter_by(name="groceries").one()
        session.add(
            TransactionORM(
                id="last-month-shop",
                date=LAST_MONTH.replace(day=10),
                name="EDEKA",
                amount=-55.0,
                category_id=groceries.id,
                is_reviewed=True,
                import_batch="test",
            )
        )
        session.commit()
    manager.engine.dispose()


def test_analytics_top_last_month(cli_runner, seeded):
    result = cli_runner("analytics", "top", "--last-month")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert (payload["year"], payload["month"]) == (LAST_MONTH.year, LAST_MONTH.month)
    assert [t["id"] for t in payload["top_transactions"]] == ["last-month-shop"]


def test_analytics_top_last_month_with_an_explicit_month_is_an_error(cli_runner, seeded):
    result = cli_runner("analytics", "top", "--last-month", "--month", "3")

    assert result.returncode == 1
    assert "error" in json.loads(result.stdout)


def test_tx_list_category_ignores_case(cli_runner, seeded):
    result = cli_runner("tx", "list", "--category", "Groceries")

    assert result.returncode == 0, result.stderr
    assert [t["id"] for t in json.loads(result.stdout)["transactions"]] == ["last-month-shop"]


def test_tx_list_unknown_category_is_an_error(cli_runner, seeded):
    result = cli_runner("tx", "list", "--category", "Grocery")

    assert result.returncode == 1
    assert json.loads(result.stdout) == {"error": "Category not found: Grocery"}
