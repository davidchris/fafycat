"""Exact-value tests for budget variance, category breakdown and year-over-year numbers.

Sign convention under test: spending is stored negative in the database. Budget variance reports
money spent as a positive ``actual``; category breakdown keeps the signed ``amount``. Both compute
a variance as ``budget - spent`` (positive means under budget).
"""

import json
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from fafycat.api import services
from fafycat.api.services import AnalyticsService
from fafycat.core.database import Base, BudgetPlanORM, CategoryORM, TransactionORM

GROCERIES, DINING, RENT, SALARY, LEGACY = 1, 2, 3, 4, 5


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


def _seed(session: Session) -> None:
    """Seed March 2025 with spending in budgeted and unbudgeted categories plus income.

    The legacy ``categories.budget`` values are deliberately different from the 2025 plans so a
    test can tell which source a number came from.
    """
    session.add_all(
        [
            CategoryORM(id=GROCERIES, name="groceries", type="spending", budget=9999.0, is_active=True),
            CategoryORM(id=DINING, name="dining", type="spending", budget=0.0, is_active=True),
            CategoryORM(id=RENT, name="rent", type="spending", budget=9999.0, is_active=True),
            CategoryORM(id=SALARY, name="salary", type="income", budget=0.0, is_active=True),
            CategoryORM(id=LEGACY, name="legacy_only", type="spending", budget=200.0, is_active=True),
            BudgetPlanORM(category_id=GROCERIES, year=2025, monthly_budget=2700.0),
            BudgetPlanORM(category_id=RENT, year=2025, monthly_budget=400.0),
            _tx("g1", date(2025, 3, 3), -1000.0, GROCERIES),
            _tx("g2", date(2025, 3, 20), -300.0, GROCERIES),
            _tx("d1", date(2025, 3, 8), -500.0, DINING),
            _tx("r1", date(2025, 3, 1), -800.0, RENT),
            _tx("s1", date(2025, 3, 28), 3000.0, SALARY),
        ]
    )
    session.commit()


@pytest.fixture
def seeded_db(tmp_data_dir: Path) -> Path:
    """Seeded database file at the ``FAFYCAT_DB_URL`` the app and CLI read."""
    db_path = tmp_data_dir / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        _seed(session)
    engine.dispose()
    return db_path


@pytest.fixture
def session(seeded_db: Path) -> Iterator[Session]:
    engine = create_engine(f"sqlite:///{seeded_db}")
    with sessionmaker(bind=engine)() as db_session:
        yield db_session
    engine.dispose()


MARCH = (date(2025, 3, 1), date(2025, 3, 31))


def _variance_of(result: dict, name: str) -> dict:
    return next(v for v in result["variances"] if v["category_name"] == name)


class TestBudgetVariance:
    def test_spending_under_budget_reports_positive_variance(self, session):
        result = AnalyticsService.get_budget_variance(session, *MARCH)

        groceries = _variance_of(result, "groceries")
        assert groceries["budget"] == pytest.approx(2700.0)
        assert groceries["actual"] == pytest.approx(1300.0)
        assert groceries["variance"] == pytest.approx(1400.0)
        assert groceries["variance_percentage"] == pytest.approx(1400.0 / 2700.0 * 100)
        assert groceries["is_overspent"] is False

    def test_spending_over_budget(self, session):
        rent = _variance_of(AnalyticsService.get_budget_variance(session, *MARCH), "rent")

        assert rent["budget"] == pytest.approx(400.0)
        assert rent["actual"] == pytest.approx(800.0)
        assert rent["variance"] == pytest.approx(-400.0)
        assert rent["variance_percentage"] == pytest.approx(-100.0)
        assert rent["is_overspent"] is True

    def test_spending_without_budget_is_overspent_by_the_full_amount(self, session):
        dining = _variance_of(AnalyticsService.get_budget_variance(session, *MARCH), "dining")

        assert dining["budget"] == pytest.approx(0.0)
        assert dining["actual"] == pytest.approx(500.0)
        assert dining["variance"] == pytest.approx(-500.0)
        assert dining["variance_percentage"] is None
        assert dining["is_overspent"] is True

    def test_legacy_category_budget_is_the_fallback_without_a_plan(self, session):
        legacy = _variance_of(AnalyticsService.get_budget_variance(session, *MARCH), "legacy_only")

        assert legacy["budget"] == pytest.approx(200.0)
        assert legacy["actual"] == pytest.approx(0.0)
        assert legacy["variance"] == pytest.approx(200.0)
        assert legacy["is_overspent"] is False

    def test_income_is_not_part_of_the_spending_variance(self, session):
        result = AnalyticsService.get_budget_variance(session, *MARCH)

        assert {v["category_name"] for v in result["variances"]} == {"groceries", "dining", "rent", "legacy_only"}

    def test_summary_totals_use_money_spent(self, session):
        summary = AnalyticsService.get_budget_variance(session, *MARCH)["summary"]

        # Budgets: groceries 2700 + rent 400 + legacy 200. Spent: 1300 + 500 + 800.
        assert summary["total_budget"] == pytest.approx(3300.0)
        assert summary["total_actual"] == pytest.approx(2600.0)
        assert summary["total_variance"] == pytest.approx(700.0)
        assert summary["total_variance_percentage"] == pytest.approx(700.0 / 3300.0 * 100)

    def test_single_category_summary_matches_the_review_example(self, session):
        """Budget 2,700 and spending 1,300 is 1,400 (about 52 %) under budget, not 4,000 / 148 %."""
        session.query(TransactionORM).filter(TransactionORM.category_id != GROCERIES).delete()
        session.query(CategoryORM).filter(CategoryORM.id != GROCERIES).update({"is_active": False})
        session.commit()

        summary = AnalyticsService.get_budget_variance(session, *MARCH)["summary"]

        assert summary["total_budget"] == pytest.approx(2700.0)
        assert summary["total_actual"] == pytest.approx(1300.0)
        assert summary["total_variance"] == pytest.approx(1400.0)
        assert summary["total_variance_percentage"] == pytest.approx(51.85, abs=0.01)

    def test_zero_total_budget_has_no_percentage(self, session):
        session.query(BudgetPlanORM).delete()
        session.query(CategoryORM).update({"budget": 0.0})
        session.commit()

        summary = AnalyticsService.get_budget_variance(session, *MARCH)["summary"]

        assert summary["total_variance"] == pytest.approx(-2600.0)
        assert summary["total_variance_percentage"] is None


class TestBudgetProration:
    """Monthly budgets count each calendar month by the share of its days inside the range."""

    def test_half_month(self, session):
        groceries = _variance_of(
            AnalyticsService.get_budget_variance(session, date(2025, 3, 1), date(2025, 3, 15)), "groceries"
        )

        assert groceries["budget"] == pytest.approx(2700.0 * 15 / 31)
        assert groceries["actual"] == pytest.approx(1000.0)

    def test_range_across_partial_and_full_months(self, session):
        groceries = _variance_of(
            AnalyticsService.get_budget_variance(session, date(2025, 1, 17), date(2025, 3, 31)), "groceries"
        )

        # 15 of 31 January days, all of February, all of March.
        assert groceries["budget"] == pytest.approx(2700.0 * (15 / 31 + 1 + 1))

    def test_full_year_is_twelve_monthly_budgets(self, session):
        groceries = _variance_of(
            AnalyticsService.get_budget_variance(session, date(2025, 1, 1), date(2025, 12, 31)), "groceries"
        )

        assert groceries["budget"] == pytest.approx(12 * 2700.0)

    def test_cross_year_range_counts_each_years_plan_even_without_transactions(self, session):
        session.add(BudgetPlanORM(category_id=GROCERIES, year=2024, monthly_budget=100.0))
        session.commit()

        groceries = _variance_of(
            AnalyticsService.get_budget_variance(session, date(2024, 12, 1), date(2025, 3, 31)), "groceries"
        )

        # December 2024 at 100 (no transactions that year) plus Jan-Mar 2025 at 2,700.
        assert groceries["budget"] == pytest.approx(100.0 + 3 * 2700.0)
        assert groceries["actual"] == pytest.approx(1300.0)
        assert groceries["variance"] == pytest.approx(100.0 + 3 * 2700.0 - 1300.0)


def test_budgeted_months_handles_the_last_representable_month():
    assert services.budgeted_months(date(9999, 12, 1), date(9999, 12, 31)) == pytest.approx(1.0)


class TestBudgetVarianceHtml:
    @pytest.fixture
    def client(self, seeded_db, app_factory):  # noqa: ARG002 - dep seeds the DB
        with TestClient(app_factory()) as test_client:
            yield test_client

    def test_total_row_shows_spent_and_variance_with_sensible_signs(self, client):
        response = client.get(
            "/api/analytics/budget-variance-html", params={"start_date": "2025-03-01", "end_date": "2025-03-31"}
        )

        assert response.status_code == 200
        total_row = response.text.split("TOTAL", 1)[1].split("</tr>", 1)[0]
        cells = [part.split("</td>", 1)[0].strip() for part in total_row.split("<td")[1:]]
        cells = [cell.split(">", 1)[1].strip() for cell in cells]
        assert cells == ["€3300.00", "€2600.00", "€700.00 (21.2%)", "Under Budget"]

    def test_unbudgeted_row_shows_negative_variance_without_percentage(self, client):
        response = client.get(
            "/api/analytics/budget-variance-html", params={"start_date": "2025-03-01", "end_date": "2025-03-31"}
        )

        dining_row = response.text.split("dining", 1)[1].split("</tr>", 1)[0]
        assert "-€500.00 (n/a)" in dining_row
        assert "Over Budget" in dining_row


def _breakdown_of(result: dict, name: str) -> dict:
    return next(c for c in result["categories"] if c["category_name"] == name)


class TestCategoryBreakdown:
    def test_percentage_is_share_of_total_spending(self, session):
        result = AnalyticsService.get_category_breakdown(session, *MARCH, category_type="spending")

        # Spent: groceries 1300, rent 800, dining 500 = 2600.
        assert _breakdown_of(result, "groceries")["percentage"] == pytest.approx(1300 / 2600 * 100)
        assert _breakdown_of(result, "rent")["percentage"] == pytest.approx(800 / 2600 * 100)
        assert _breakdown_of(result, "dining")["percentage"] == pytest.approx(500 / 2600 * 100)

    def test_percentage_is_share_within_each_type_when_unfiltered(self, session):
        result = AnalyticsService.get_category_breakdown(session, *MARCH)

        assert _breakdown_of(result, "groceries")["percentage"] == pytest.approx(1300 / 2600 * 100)
        assert _breakdown_of(result, "salary")["percentage"] == pytest.approx(100.0)

    def test_budget_variance_is_budget_minus_spent(self, session):
        result = AnalyticsService.get_category_breakdown(session, *MARCH, category_type="spending")

        rent = _breakdown_of(result, "rent")
        assert rent["amount"] == pytest.approx(-800.0)
        assert rent["budget"] == pytest.approx(400.0)
        assert rent["budget_variance"] == pytest.approx(-400.0)

        groceries = _breakdown_of(result, "groceries")
        assert groceries["budget"] == pytest.approx(2700.0)
        assert groceries["budget_variance"] == pytest.approx(1400.0)

        dining = _breakdown_of(result, "dining")
        assert dining["budget"] == pytest.approx(0.0)
        assert dining["budget_variance"] == pytest.approx(-500.0)

    def test_budget_is_prorated_like_the_variance_endpoint(self, session):
        result = AnalyticsService.get_category_breakdown(session, date(2025, 3, 1), date(2025, 3, 15))

        groceries = _breakdown_of(result, "groceries")
        assert groceries["budget"] == pytest.approx(2700.0 * 15 / 31)
        assert groceries["budget_variance"] == pytest.approx(2700.0 * 15 / 31 - 1000.0)

    def test_income_has_no_budget_variance(self, session):
        salary = _breakdown_of(AnalyticsService.get_category_breakdown(session, *MARCH), "salary")

        assert salary["amount"] == pytest.approx(3000.0)
        assert salary["budget_variance"] is None


class TestYearOverYearLeapDay:
    @pytest.fixture
    def leap_session(self, db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Session:
        class _Today(date):
            @classmethod
            def today(cls) -> date:
                return date(2028, 3, 1)

        monkeypatch.setattr(services, "date", _Today)
        db_session.add_all(
            [
                CategoryORM(id=GROCERIES, name="groceries", type="spending", budget=0.0, is_active=True),
                _tx("y27a", date(2027, 2, 28), -30.0, GROCERIES),
                _tx("y27b", date(2027, 3, 10), -50.0, GROCERIES),
                _tx("y28", date(2028, 2, 29), -100.0, GROCERIES),
            ]
        )
        db_session.commit()
        return db_session

    def test_latest_transaction_on_29_february_clamps_to_28_february(self, leap_session):
        result = AnalyticsService.get_year_over_year_comparison(leap_session, years=[2027, 2028])

        groceries = result["categories"][0]
        assert groceries["yearly_data"]["2027"]["total"] == pytest.approx(-30.0)
        assert groceries["yearly_data"]["2028"]["total"] == pytest.approx(-100.0)
        assert result["summary"]["comparison_end_date"] == "2028-02-29"
        assert result["unreviewed"]["date_range"]["windows"] == [
            {"start_date": "2027-01-01", "end_date": "2027-02-28"},
            {"start_date": "2028-01-01", "end_date": "2028-02-29"},
        ]


@pytest.mark.integration
class TestCli:
    def test_variance_and_breakdown_report_the_same_numbers(self, seeded_db, cli_runner):  # noqa: ARG002
        variance = cli_runner("analytics", "variance", "--month", "2025-03")
        breakdown = cli_runner("analytics", "breakdown", "--month", "2025-03", "--type", "spending")
        assert variance.returncode == 0, variance.stderr
        assert breakdown.returncode == 0, breakdown.stderr

        summary = json.loads(variance.stdout)["summary"]
        assert summary["total_budget"] == pytest.approx(3300.0)
        assert summary["total_actual"] == pytest.approx(2600.0)
        assert summary["total_variance"] == pytest.approx(700.0)

        categories = {c["category_name"]: c for c in json.loads(breakdown.stdout)["categories"]}
        assert categories["rent"]["budget_variance"] == pytest.approx(-400.0)
        assert categories["groceries"]["percentage"] == pytest.approx(50.0)
