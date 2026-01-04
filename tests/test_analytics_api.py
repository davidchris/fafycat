"""Tests for Analytics API endpoints."""

import os
import tempfile
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from fafycat.core.database import Base, CategoryORM, TransactionORM  # noqa: F401 - sessionmaker used


@pytest.fixture(scope="function")
def temp_db_file():
    """Create a temporary database file."""
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    yield db_path
    os.unlink(db_path)


@pytest.fixture
def test_db_with_yoy_data(temp_db_file):
    """Create a test database with multi-year transaction data for YoY testing."""
    engine = create_engine(f"sqlite:///{temp_db_file}", echo=False)
    Base.metadata.create_all(engine)

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()

    # Add test categories
    categories = [
        CategoryORM(id=1, name="groceries", type="spending", budget=500.0, is_active=True),
        CategoryORM(id=2, name="salary", type="income", budget=0.0, is_active=True),
        CategoryORM(id=3, name="dining", type="spending", budget=200.0, is_active=True),
    ]

    for cat in categories:
        session.add(cat)

    # Add transactions for 2023
    for month in range(1, 13):
        session.add(
            TransactionORM(
                id=f"txn_2023_{month}_groceries",
                date=date(2023, month, 15),
                value_date=date(2023, month, 15),
                name="Supermarket ABC",
                purpose="Weekly shopping",
                amount=-150.00,
                currency="EUR",
                category_id=1,  # Groceries
                is_reviewed=True,
                imported_at=datetime.now(),
                import_batch="batch_2023",
            )
        )
        session.add(
            TransactionORM(
                id=f"txn_2023_{month}_salary",
                date=date(2023, month, 1),
                value_date=date(2023, month, 1),
                name="Employer Inc",
                purpose="Monthly salary",
                amount=3000.00,
                currency="EUR",
                category_id=2,  # Salary
                is_reviewed=True,
                imported_at=datetime.now(),
                import_batch="batch_2023",
            )
        )

    # Add transactions for 2024 (with 10% increase in groceries)
    for month in range(1, 13):
        session.add(
            TransactionORM(
                id=f"txn_2024_{month}_groceries",
                date=date(2024, month, 15),
                value_date=date(2024, month, 15),
                name="Supermarket ABC",
                purpose="Weekly shopping",
                amount=-165.00,  # 10% increase
                currency="EUR",
                category_id=1,  # Groceries
                is_reviewed=True,
                imported_at=datetime.now(),
                import_batch="batch_2024",
            )
        )
        session.add(
            TransactionORM(
                id=f"txn_2024_{month}_salary",
                date=date(2024, month, 1),
                value_date=date(2024, month, 1),
                name="Employer Inc",
                purpose="Monthly salary",
                amount=3150.00,  # 5% increase
                currency="EUR",
                category_id=2,  # Salary
                is_reviewed=True,
                imported_at=datetime.now(),
                import_batch="batch_2024",
            )
        )

    session.commit()
    session.close()
    engine.dispose()

    yield temp_db_file


@pytest.fixture
def test_client(test_db_with_yoy_data):
    """Create a test client with multi-year data."""
    temp_model_dir = tempfile.mkdtemp()

    # Set environment variables BEFORE importing the app
    os.environ["FAFYCAT_DB_URL"] = f"sqlite:///{test_db_with_yoy_data}"
    os.environ["FAFYCAT_ENV"] = "testing"
    os.environ["FAFYCAT_MODEL_DIR"] = temp_model_dir

    from main import create_app

    app = create_app()

    with TestClient(app) as client:
        yield client

    # Cleanup
    import shutil

    shutil.rmtree(temp_model_dir, ignore_errors=True)


class TestYearOverYearEndpoint:
    """Tests for /api/analytics/year-over-year endpoint."""

    def test_basic_yoy_response(self, test_client):
        """Test basic YoY comparison returns expected structure."""
        response = test_client.get("/api/analytics/year-over-year")
        assert response.status_code == 200

        data = response.json()
        assert "categories" in data
        assert "summary" in data
        assert "years" in data["summary"]
        assert "total_by_year" in data["summary"]

    def test_yoy_with_category_type_filter(self, test_client):
        """Test YoY comparison with category type filter."""
        response = test_client.get("/api/analytics/year-over-year?category_type=spending")
        assert response.status_code == 200

        data = response.json()
        assert data["summary"]["category_type_filter"] == "spending"
        # All returned categories should be spending type
        for category in data["categories"]:
            assert category["type"] == "spending"

    def test_yoy_with_years_filter(self, test_client):
        """Test YoY comparison with specific years."""
        response = test_client.get("/api/analytics/year-over-year?years=2023,2024")
        assert response.status_code == 200

        data = response.json()
        assert 2023 in data["summary"]["years"]
        assert 2024 in data["summary"]["years"]

    def test_yoy_invalid_years_format(self, test_client):
        """Test error handling for invalid years format."""
        response = test_client.get("/api/analytics/year-over-year?years=invalid,years")
        assert response.status_code == 400
        assert "Invalid years format" in response.json()["detail"]

    def test_yoy_categories_have_yearly_data(self, test_client):
        """Test that categories have yearly data with expected fields."""
        response = test_client.get("/api/analytics/year-over-year?years=2023,2024")
        assert response.status_code == 200

        data = response.json()
        assert len(data["categories"]) > 0

        # Check first category has expected structure
        category = data["categories"][0]
        assert "name" in category
        assert "type" in category
        assert "yearly_data" in category
        assert "changes" in category

        # Check yearly data has expected fields
        for year_data in category["yearly_data"].values():
            assert "total" in year_data
            assert "monthly_avg" in year_data
            assert "transactions" in year_data


class TestCategoryCumulativeEndpoint:
    """Tests for /api/analytics/category-cumulative endpoint."""

    def test_cumulative_basic_response(self, test_client):
        """Test basic cumulative data response."""
        response = test_client.get("/api/analytics/category-cumulative?category_id=1")
        assert response.status_code == 200

        data = response.json()
        assert "years" in data
        assert "monthly_data" in data
        assert "category_name" in data

    def test_cumulative_missing_category_id(self, test_client):
        """Test error when category_id is missing."""
        response = test_client.get("/api/analytics/category-cumulative")
        assert response.status_code == 422  # Validation error

    def test_cumulative_with_years_filter(self, test_client):
        """Test cumulative data with specific years."""
        response = test_client.get("/api/analytics/category-cumulative?category_id=1&years=2023,2024")
        assert response.status_code == 200

        data = response.json()
        assert "2023" in data["monthly_data"] or "2024" in data["monthly_data"]

    def test_cumulative_monthly_data_structure(self, test_client):
        """Test that monthly data has expected structure."""
        response = test_client.get("/api/analytics/category-cumulative?category_id=1&years=2024")
        assert response.status_code == 200

        data = response.json()
        if "2024" in data["monthly_data"]:
            year_data = data["monthly_data"]["2024"]
            assert "monthly_totals" in year_data
            assert "cumulative" in year_data
            assert len(year_data["monthly_totals"]) == 12
            assert len(year_data["cumulative"]) == 12


class TestAvailableYearsEndpoint:
    """Tests for /api/analytics/available-years endpoint."""

    def test_available_years_response(self, test_client):
        """Test available years endpoint returns expected structure."""
        response = test_client.get("/api/analytics/available-years")
        assert response.status_code == 200

        data = response.json()
        assert "years" in data
        assert isinstance(data["years"], list)

    def test_available_years_contains_test_data_years(self, test_client):
        """Test that available years includes our test data years."""
        response = test_client.get("/api/analytics/available-years")
        assert response.status_code == 200

        data = response.json()
        # Our test data has 2023 and 2024
        assert 2023 in data["years"]
        assert 2024 in data["years"]

    def test_available_years_sorted_descending(self, test_client):
        """Test that years are sorted in descending order (most recent first)."""
        response = test_client.get("/api/analytics/available-years")
        assert response.status_code == 200

        data = response.json()
        years = data["years"]
        assert years == sorted(years, reverse=True)
