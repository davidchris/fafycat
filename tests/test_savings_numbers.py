"""Exact-value tests for the saving sign: saving and de-saving.

Amounts are stored from the checking account's view. A transfer to savings is negative (saving),
a transfer back from savings is positive (de-saving). Savings tracking reports net saved, which is
``-sum(amount)`` of the saving categories: positive means saving, negative means de-saving.
"""

import json
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from fafycat.api.services import AnalyticsService
from fafycat.core.database import Base, BudgetPlanORM, CategoryORM, TransactionORM

SAVINGS, SALARY, GROCERIES = 1, 2, 3


def _tx(tx_id: str, day: date, amount: float, category_id: int) -> TransactionORM:
    return TransactionORM(
        id=tx_id,
        date=day,
        value_date=day,
        name=f"merchant {tx_id}",
        purpose="",
        amount=amount,
        currency="EUR",
        category_id=category_id,
        is_reviewed=True,
        imported_at=datetime(2025, 1, 1),
        import_batch="batch",
    )


@pytest.fixture
def seeded_db(tmp_data_dir: Path) -> Path:
    """March 2025 nets 300 saved (-500 out, +200 back); April 2025 de-saves 400."""
    db_path = tmp_data_dir / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        session.add_all(
            [
                CategoryORM(id=SAVINGS, name="savings_account", type="saving", budget=0.0, is_active=True),
                CategoryORM(id=SALARY, name="salary", type="income", budget=0.0, is_active=True),
                CategoryORM(id=GROCERIES, name="groceries", type="spending", budget=0.0, is_active=True),
                BudgetPlanORM(category_id=SAVINGS, year=2025, monthly_budget=1000.0),
                BudgetPlanORM(category_id=SALARY, year=2025, monthly_budget=2500.0),
                BudgetPlanORM(category_id=GROCERIES, year=2025, monthly_budget=400.0),
                _tx("out", date(2025, 3, 2), -500.0, SAVINGS),
                _tx("back", date(2025, 3, 20), 200.0, SAVINGS),
                _tx("desave", date(2025, 4, 10), 400.0, SAVINGS),
                _tx("pay", date(2025, 3, 28), 3000.0, SALARY),
                _tx("food", date(2025, 3, 5), -100.0, GROCERIES),
            ]
        )
        session.commit()
    engine.dispose()
    return db_path


@pytest.fixture
def session(seeded_db: Path) -> Iterator[Session]:
    engine = create_engine(f"sqlite:///{seeded_db}")
    with sessionmaker(bind=engine)() as db_session:
        yield db_session
    engine.dispose()


def _month(result: dict, month: str) -> dict:
    return next(m for m in result["monthly_savings"] if m["month"] == month)


class TestSavingsTracking:
    def test_monthly_amount_and_cumulative_are_net_saved(self, session):
        result = AnalyticsService.get_savings_tracking(session, start_date=date(2025, 3, 1), end_date=date(2025, 4, 30))

        march, april = _month(result, "2025-03"), _month(result, "2025-04")
        assert march["amount"] == pytest.approx(300.0)
        assert march["cumulative_amount"] == pytest.approx(300.0)
        assert april["amount"] == pytest.approx(-400.0)
        assert april["cumulative_amount"] == pytest.approx(-100.0)

    def test_statistics_count_only_saving_months_and_report_de_saving_months(self, session):
        stats = AnalyticsService.get_savings_tracking(session, start_date=date(2025, 3, 1), end_date=date(2025, 5, 31))[
            "statistics"
        ]

        assert stats["total_savings"] == pytest.approx(-100.0)
        assert stats["months_with_savings"] == 1
        assert stats["months_with_desaving"] == 1
        assert stats["average_monthly"] == pytest.approx(300.0)
        assert stats["median_monthly"] == pytest.approx(300.0)

    def test_cli_reports_net_saved(self, seeded_db, cli_runner):  # noqa: ARG002 - fixture seeds the DB
        result = cli_runner("analytics", "savings", "--start", "2025-03-01", "--end", "2025-04-30")

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert [(m["month"], m["amount"], m["cumulative_amount"]) for m in payload["monthly_savings"]] == [
            ("2025-03", 300.0, 300.0),
            ("2025-04", -400.0, -100.0),
        ]


class TestMonthlySummary:
    def test_saving_stays_a_signed_cash_flow(self, session):
        result = AnalyticsService.get_monthly_summary(session, year=2025)

        march = next(m for m in result["monthly_data"] if m["month"] == "2025-03")
        assert march["saving"] == pytest.approx(-300.0)
        assert result["yearly_totals"]["saving"] == pytest.approx(100.0)


class TestBudgetVarianceScope:
    @pytest.fixture
    def client(self, seeded_db, app_factory):  # noqa: ARG002 - dep seeds the DB
        with TestClient(app_factory()) as test_client:
            yield test_client

    def test_saving_and_income_plans_stay_out_of_the_spending_variance(self, client):
        response = client.get(
            "/api/analytics/budget-variance", params={"start_date": "2025-03-01", "end_date": "2025-03-31"}
        )

        assert response.status_code == 200
        payload = response.json()
        assert [v["category_name"] for v in payload["variances"]] == ["groceries"]
        assert payload["summary"]["total_budget"] == pytest.approx(400.0)
        assert payload["summary"]["total_actual"] == pytest.approx(100.0)
        assert payload["summary"]["total_variance"] == pytest.approx(300.0)
