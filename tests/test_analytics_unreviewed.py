"""Tests for the unreviewed-transaction handling of the analytics stack.

The seeded database holds, for a single year, one reviewed and one unreviewed transaction per
category, so every aggregation must differ in a predictable way between the two modes.
"""

from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from fafycat.api.services import AnalyticsService
from fafycat.core.database import Base, CategoryORM, TransactionORM

YEAR = 2024
REVIEWED_GROCERIES = -100.0
UNREVIEWED_GROCERIES = -40.0
REVIEWED_SALARY = 3000.0
UNREVIEWED_SALARY = 500.0
REVIEWED_SAVING = -200.0
UNREVIEWED_SAVING = -50.0

# One reviewed plus one unreviewed transaction per category, in each of the 12 months.
UNREVIEWED_COUNT_PER_YEAR = 36
UNREVIEWED_ABS_AMOUNT_PER_YEAR = 12 * (abs(UNREVIEWED_GROCERIES) + abs(UNREVIEWED_SALARY) + abs(UNREVIEWED_SAVING))


def _seed(session: Session) -> None:
    """Insert categories and paired reviewed/unreviewed transactions for ``YEAR``."""
    session.add_all(
        [
            CategoryORM(id=1, name="groceries", type="spending", budget=500.0, is_active=True),
            CategoryORM(id=2, name="salary", type="income", budget=0.0, is_active=True),
            CategoryORM(id=3, name="savings_account", type="saving", budget=0.0, is_active=True),
        ]
    )

    rows = (
        (1, REVIEWED_GROCERIES, UNREVIEWED_GROCERIES),
        (2, REVIEWED_SALARY, UNREVIEWED_SALARY),
        (3, REVIEWED_SAVING, UNREVIEWED_SAVING),
    )

    for month in range(1, 13):
        for category_id, reviewed_amount, unreviewed_amount in rows:
            session.add(
                TransactionORM(
                    id=f"reviewed_{category_id}_{month}",
                    date=date(YEAR, month, 5),
                    value_date=date(YEAR, month, 5),
                    name="Reviewed merchant",
                    purpose="reviewed",
                    amount=reviewed_amount,
                    currency="EUR",
                    category_id=category_id,
                    is_reviewed=True,
                    imported_at=datetime.now(),
                    import_batch="batch",
                )
            )
            # Unreviewed rows only carry a prediction — that is what analytics silently counted.
            session.add(
                TransactionORM(
                    id=f"unreviewed_{category_id}_{month}",
                    date=date(YEAR, month, 6),
                    value_date=date(YEAR, month, 6),
                    name="Guessed merchant",
                    purpose="unreviewed",
                    amount=unreviewed_amount,
                    currency="EUR",
                    predicted_category_id=category_id,
                    confidence_score=0.4,
                    is_reviewed=False,
                    imported_at=datetime.now(),
                    import_batch="batch",
                )
            )

    session.commit()


@pytest.fixture
def unreviewed_db_file(tmp_data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Seeded database file with mixed reviewed/unreviewed transactions."""
    db_path = tmp_data_dir / "unreviewed.db"
    monkeypatch.setenv("FAFYCAT_DB_URL", f"sqlite:///{db_path}")

    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    _seed(session)
    session.close()
    engine.dispose()
    return db_path


@pytest.fixture
def analytics_session(unreviewed_db_file: Path):
    """Session bound to the seeded unreviewed database."""
    engine = create_engine(f"sqlite:///{unreviewed_db_file}", echo=False)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def unreviewed_client(unreviewed_db_file, app_factory):  # noqa: ARG001 - dep seeds the DB
    """Test client wired to the seeded unreviewed database."""
    app = app_factory()
    with TestClient(app) as client:
        yield client


class TestServiceAggregations:
    """Each aggregation must report the unreviewed share and honour ``include_unreviewed``."""

    def test_monthly_summary(self, analytics_session):
        included = AnalyticsService.get_monthly_summary(analytics_session, year=YEAR)
        reviewed_only = AnalyticsService.get_monthly_summary(analytics_session, year=YEAR, include_unreviewed=False)

        assert included["yearly_totals"]["spending"] == pytest.approx(12 * (REVIEWED_GROCERIES + UNREVIEWED_GROCERIES))
        assert reviewed_only["yearly_totals"]["spending"] == pytest.approx(12 * REVIEWED_GROCERIES)
        assert included["yearly_totals"]["income"] == pytest.approx(12 * (REVIEWED_SALARY + UNREVIEWED_SALARY))
        assert reviewed_only["yearly_totals"]["income"] == pytest.approx(12 * REVIEWED_SALARY)

        january = included["monthly_data"][0]
        assert january["unreviewed_count"] == 3
        assert january["unreviewed_amount"] == pytest.approx(
            UNREVIEWED_GROCERIES + UNREVIEWED_SALARY + UNREVIEWED_SAVING
        )

        assert included["unreviewed"]["count"] == UNREVIEWED_COUNT_PER_YEAR
        assert included["unreviewed"]["amount"] == pytest.approx(UNREVIEWED_ABS_AMOUNT_PER_YEAR)
        assert included["unreviewed"]["included"] is True
        # The summary still describes the range when the rows were left out.
        assert reviewed_only["unreviewed"]["count"] == UNREVIEWED_COUNT_PER_YEAR
        assert reviewed_only["unreviewed"]["included"] is False

    def test_category_breakdown(self, analytics_session):
        start, end = date(YEAR, 1, 1), date(YEAR, 12, 31)
        included = AnalyticsService.get_category_breakdown(analytics_session, start, end, "spending")
        reviewed_only = AnalyticsService.get_category_breakdown(
            analytics_session, start, end, "spending", include_unreviewed=False
        )

        groceries = included["categories"][0]
        assert groceries["amount"] == pytest.approx(12 * (REVIEWED_GROCERIES + UNREVIEWED_GROCERIES))
        assert groceries["unreviewed_amount"] == pytest.approx(12 * UNREVIEWED_GROCERIES)
        assert groceries["unreviewed_count"] == 12
        assert groceries["transaction_count"] == 24

        reviewed_groceries = reviewed_only["categories"][0]
        assert reviewed_groceries["amount"] == pytest.approx(12 * REVIEWED_GROCERIES)
        assert reviewed_groceries["unreviewed_amount"] == pytest.approx(0.0)
        assert reviewed_groceries["unreviewed_count"] == 0
        assert reviewed_groceries["transaction_count"] == 12

        assert included["unreviewed"]["count"] == UNREVIEWED_COUNT_PER_YEAR
        assert reviewed_only["unreviewed"]["included"] is False

    def test_budget_variance(self, analytics_session):
        start, end = date(YEAR, 1, 1), date(YEAR, 12, 31)
        included = AnalyticsService.get_budget_variance(analytics_session, start, end)
        reviewed_only = AnalyticsService.get_budget_variance(analytics_session, start, end, include_unreviewed=False)

        groceries = next(v for v in included["variances"] if v["category_name"] == "groceries")
        assert groceries["actual"] == pytest.approx(12 * abs(REVIEWED_GROCERIES + UNREVIEWED_GROCERIES))
        assert groceries["unreviewed_amount"] == pytest.approx(12 * abs(UNREVIEWED_GROCERIES))
        assert groceries["unreviewed_count"] == 12

        reviewed_groceries = next(v for v in reviewed_only["variances"] if v["category_name"] == "groceries")
        assert reviewed_groceries["actual"] == pytest.approx(12 * abs(REVIEWED_GROCERIES))
        assert reviewed_groceries["unreviewed_count"] == 0

        assert included["unreviewed"]["count"] == UNREVIEWED_COUNT_PER_YEAR
        assert reviewed_only["unreviewed"]["included"] is False

    def test_savings_tracking(self, analytics_session):
        included = AnalyticsService.get_savings_tracking(analytics_session, year=YEAR)
        reviewed_only = AnalyticsService.get_savings_tracking(analytics_session, year=YEAR, include_unreviewed=False)

        assert included["statistics"]["total_savings"] == pytest.approx(12 * (REVIEWED_SAVING + UNREVIEWED_SAVING))
        assert reviewed_only["statistics"]["total_savings"] == pytest.approx(12 * REVIEWED_SAVING)

        january = included["monthly_savings"][0]
        assert january["unreviewed_amount"] == pytest.approx(UNREVIEWED_SAVING)
        assert january["unreviewed_count"] == 1
        assert reviewed_only["monthly_savings"][0]["unreviewed_count"] == 0

        assert included["unreviewed"]["count"] == UNREVIEWED_COUNT_PER_YEAR
        assert reviewed_only["unreviewed"]["included"] is False

    def test_year_over_year(self, analytics_session):
        included = AnalyticsService.get_year_over_year_comparison(analytics_session, years=[YEAR])
        reviewed_only = AnalyticsService.get_year_over_year_comparison(
            analytics_session, years=[YEAR], include_unreviewed=False
        )

        groceries = next(c for c in included["categories"] if c["name"] == "groceries")
        year_data = groceries["yearly_data"][str(YEAR)]
        assert year_data["total"] == pytest.approx(12 * (REVIEWED_GROCERIES + UNREVIEWED_GROCERIES))
        assert year_data["unreviewed_amount"] == pytest.approx(12 * UNREVIEWED_GROCERIES)
        assert year_data["unreviewed_count"] == 12
        assert groceries["unreviewed_count"] == 12

        reviewed_groceries = next(c for c in reviewed_only["categories"] if c["name"] == "groceries")
        assert reviewed_groceries["yearly_data"][str(YEAR)]["total"] == pytest.approx(12 * REVIEWED_GROCERIES)
        assert reviewed_groceries["unreviewed_count"] == 0

        assert included["unreviewed"]["count"] == UNREVIEWED_COUNT_PER_YEAR
        assert reviewed_only["unreviewed"]["included"] is False

    def test_top_transactions(self, analytics_session):
        included = AnalyticsService.get_top_transactions_by_month(analytics_session, year=YEAR, month=1, limit=5)
        reviewed_only = AnalyticsService.get_top_transactions_by_month(
            analytics_session, year=YEAR, month=1, limit=5, include_unreviewed=False
        )

        assert included["transactions_count"] == 2
        assert included["total_spending"] == pytest.approx(abs(REVIEWED_GROCERIES + UNREVIEWED_GROCERIES))
        assert {t["is_reviewed"] for t in included["top_transactions"]} == {True, False}

        assert reviewed_only["transactions_count"] == 1
        assert reviewed_only["total_spending"] == pytest.approx(abs(REVIEWED_GROCERIES))
        assert all(t["is_reviewed"] for t in reviewed_only["top_transactions"])

        assert included["unreviewed"]["count"] == 3  # One unreviewed row per category in January.
        assert reviewed_only["unreviewed"]["included"] is False

    def test_category_cumulative(self, analytics_session):
        included = AnalyticsService.get_category_cumulative_data(analytics_session, category_id=1, years=[YEAR])
        reviewed_only = AnalyticsService.get_category_cumulative_data(
            analytics_session, category_id=1, years=[YEAR], include_unreviewed=False
        )

        assert included["monthly_data"][str(YEAR)]["cumulative"][11] == pytest.approx(
            12 * (REVIEWED_GROCERIES + UNREVIEWED_GROCERIES)
        )
        assert reviewed_only["monthly_data"][str(YEAR)]["cumulative"][11] == pytest.approx(12 * REVIEWED_GROCERIES)
        assert included["unreviewed"]["count"] == UNREVIEWED_COUNT_PER_YEAR
        assert reviewed_only["unreviewed"]["included"] is False


class TestEndpointQueryParam:
    """``include_unreviewed`` must be reachable over HTTP on every analytics endpoint."""

    @pytest.mark.parametrize(
        ("path", "params"),
        [
            ("/api/analytics/monthly-summary", {"year": YEAR}),
            ("/api/analytics/category-breakdown", {"start_date": f"{YEAR}-01-01", "end_date": f"{YEAR}-12-31"}),
            ("/api/analytics/budget-variance", {"year": YEAR}),
            ("/api/analytics/savings-tracking", {"year": YEAR}),
            ("/api/analytics/year-over-year", {"years": str(YEAR)}),
            ("/api/analytics/top-transactions", {"year": YEAR, "month": 1}),
            ("/api/analytics/category-cumulative", {"category_id": 1, "years": str(YEAR)}),
        ],
    )
    def test_endpoint_reports_unreviewed_summary(self, unreviewed_client, path, params):
        included = unreviewed_client.get(path, params=params)
        excluded = unreviewed_client.get(path, params={**params, "include_unreviewed": "false"})

        assert included.status_code == 200
        assert excluded.status_code == 200
        assert included.json()["unreviewed"]["included"] is True
        assert excluded.json()["unreviewed"]["included"] is False
        assert included.json()["unreviewed"]["count"] == excluded.json()["unreviewed"]["count"]

    def test_breakdown_numbers_change_with_the_flag(self, unreviewed_client):
        params = {"start_date": f"{YEAR}-01-01", "end_date": f"{YEAR}-12-31", "category_type": "spending"}
        included = unreviewed_client.get("/api/analytics/category-breakdown", params=params).json()
        excluded = unreviewed_client.get(
            "/api/analytics/category-breakdown", params={**params, "include_unreviewed": "false"}
        ).json()

        assert included["categories"][0]["amount"] != excluded["categories"][0]["amount"]
        assert excluded["categories"][0]["amount"] == pytest.approx(12 * REVIEWED_GROCERIES)

    def test_variance_html_shows_alert_and_share(self, unreviewed_client):
        response = unreviewed_client.get(
            "/api/analytics/budget-variance-html",
            params={"start_date": f"{YEAR}-01-01", "end_date": f"{YEAR}-12-31"},
        )

        assert response.status_code == 200
        assert "alert alert-warning" in response.text
        assert "counted under their predicted category" in response.text
        assert "unreviewed" in response.text

    def test_variance_html_notes_exclusion(self, unreviewed_client):
        response = unreviewed_client.get(
            "/api/analytics/budget-variance-html",
            params={"start_date": f"{YEAR}-01-01", "end_date": f"{YEAR}-12-31", "include_unreviewed": "false"},
        )

        assert response.status_code == 200
        assert "alert alert-warning" not in response.text
        assert "excluded from these numbers" in response.text


class TestAnalyticsPage:
    """The page must ship the toggle and let the controller render the alert."""

    def test_page_has_toggle_and_alert_container(self, unreviewed_client):
        response = unreviewed_client.get("/analytics")

        assert response.status_code == 200
        assert 'id="exclude-unreviewed-toggle"' in response.text
        assert "Exclude unreviewed" in response.text
        assert 'id="unreviewed-alert-container"' in response.text
        assert "onchange=" not in response.text

    def test_controller_script_drives_the_alert(self):
        script = (Path(__file__).parent.parent / "src" / "fafycat" / "static" / "js" / "analytics_page.js").read_text()

        assert "include_unreviewed" in script
        assert "counted under their predicted category" in script
        assert "exclude-unreviewed-toggle" in script


class TestHomePage:
    """The Review card must surface the current month's unreviewed backlog."""

    def test_card_shows_count_when_present(self):
        from fafycat.web.pages.home_page import render_home_page

        assert "7 unreviewed this month" in render_home_page(unreviewed_this_month=7)

    def test_card_stays_clean_when_zero(self):
        from fafycat.web.pages.home_page import render_home_page

        page = render_home_page(unreviewed_this_month=0)
        assert "unreviewed this month" not in page
        assert "workflow-card" in page

    def test_home_route_counts_current_month(self, unreviewed_client, analytics_session):
        today = date.today()
        analytics_session.add(
            TransactionORM(
                id="unreviewed_current_month",
                date=today,
                value_date=today,
                name="Guessed merchant",
                purpose="unreviewed",
                amount=-12.0,
                currency="EUR",
                predicted_category_id=1,
                is_reviewed=False,
                imported_at=datetime.now(),
                import_batch="batch",
            )
        )
        analytics_session.commit()

        response = unreviewed_client.get("/")

        assert response.status_code == 200
        assert "1 unreviewed this month" in response.text


class TestNoticeRendering:
    """The shared HTML notice must stay silent when nothing is unreviewed."""

    def test_no_notice_without_unreviewed_rows(self):
        from fafycat.api.analytics import _render_unreviewed_notice

        assert _render_unreviewed_notice({"count": 0, "amount": 0.0, "included": True}) == ""

    def test_warning_when_counted(self):
        from fafycat.api.analytics import _render_unreviewed_notice

        notice = _render_unreviewed_notice({"count": 4, "amount": 120.5, "included": True})
        assert "alert alert-warning" in notice
        assert "4 unreviewed transactions" in notice
        assert 'href="/review"' in notice

    def test_muted_note_when_excluded(self):
        from fafycat.api.analytics import _render_unreviewed_notice

        notice = _render_unreviewed_notice({"count": 4, "amount": 120.5, "included": False})
        assert "text-secondary" in notice
        assert "excluded from these numbers" in notice


def _txn(session: Session, txn_id: str, day: date, amount: float, *, reviewed: bool, category_id: int = 1) -> None:
    session.add(
        TransactionORM(
            id=txn_id,
            date=day,
            value_date=day,
            name="m",
            purpose="",
            amount=amount,
            currency="EUR",
            category_id=category_id if reviewed else None,
            predicted_category_id=category_id,
            confidence_score=0.4,
            is_reviewed=reviewed,
            imported_at=datetime.now(),
            import_batch="batch",
        )
    )


class TestYearOverYearReviewFilterConsistency:
    """The reviewed-only view must divide by, and warn about, the same rows it totals."""

    def test_months_with_only_unreviewed_activity_do_not_dilute_the_reviewed_average(self, db_session):
        db_session.add(CategoryORM(id=1, name="groceries", type="spending", budget=0.0, is_active=True))
        _txn(db_session, "r1", date(2020, 1, 5), -100.0, reviewed=True)
        _txn(db_session, "r2", date(2020, 2, 5), -100.0, reviewed=True)
        _txn(db_session, "u3", date(2020, 3, 5), -40.0, reviewed=False)
        db_session.commit()

        reviewed_only = AnalyticsService.get_year_over_year_comparison(
            db_session, years=[2020], include_unreviewed=False
        )

        year_data = reviewed_only["categories"][0]["yearly_data"]["2020"]
        assert year_data["months_with_data"] == 2
        assert year_data["monthly_avg"] == pytest.approx(-100.0)

    def test_unreviewed_summary_uses_the_aligned_comparison_window(self, db_session):
        current_year = date.today().year
        db_session.add(CategoryORM(id=1, name="groceries", type="spending", budget=0.0, is_active=True))
        _txn(db_session, "now", date(current_year, 1, 15), -100.0, reviewed=True)
        _txn(db_session, "inside", date(current_year - 1, 1, 10), -40.0, reviewed=False)
        _txn(db_session, "outside", date(current_year - 1, 12, 20), -70.0, reviewed=False)
        db_session.commit()

        result = AnalyticsService.get_year_over_year_comparison(db_session, years=[current_year - 1, current_year])

        assert result["summary"]["comparison_end_date"] == date(current_year, 1, 15).isoformat()
        assert result["unreviewed"]["count"] == 1
        assert result["unreviewed"]["amount"] == pytest.approx(40.0)
        assert result["unreviewed"]["date_range"]["windows"] == [
            {"start_date": f"{current_year - 1}-01-01", "end_date": f"{current_year - 1}-01-15"},
            {"start_date": f"{current_year}-01-01", "end_date": f"{current_year}-01-15"},
        ]

    def test_empty_database_keeps_the_windows_shape(self, db_session):
        result = AnalyticsService.get_year_over_year_comparison(db_session, years=[])

        assert result["unreviewed"] == {"count": 0, "amount": 0.0, "included": True, "date_range": {"windows": []}}
