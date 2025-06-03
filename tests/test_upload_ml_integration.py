"""Tests for ML integration in upload workflow."""

import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from fafycat.core.database import Base, CategoryORM, TransactionORM
from fafycat.core.models import TransactionPrediction


@pytest.fixture
def test_db():
    """Create a test database."""
    engine = create_engine("sqlite:///:memory:", echo=False, connect_args={"check_same_thread": False})
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

    session.commit()
    yield session
    session.close()


@pytest.fixture
def mock_categorizer():
    """Create a mock categorizer for testing."""
    categorizer = MagicMock()
    categorizer.is_trained = True

    def mock_predict(transactions):
        predictions = []
        for txn in transactions:
            # Simple rule: restaurants get dining, everything else gets groceries
            if "restaurant" in txn.name.lower():
                category_id = 3  # Dining
                confidence = 0.9
            else:
                category_id = 1  # Groceries
                confidence = 0.8

            pred = TransactionPrediction(
                transaction_id=txn.generate_id(),
                predicted_category_id=category_id,
                confidence_score=confidence,
                feature_contributions={"merchant_name": 0.8, "amount": 0.2},
            )
            predictions.append(pred)
        return predictions

    categorizer.predict_with_confidence = mock_predict
    return categorizer


@pytest.fixture
def test_client_with_ml(test_db, mock_categorizer):
    """Create a test client with ML integration."""
    from main import create_app

    app = create_app()

    # Override database dependency
    def get_test_db():
        return test_db

    # Mock the categorizer
    with patch("api.ml.get_categorizer", return_value=mock_categorizer):
        from api.dependencies import get_db_session

        app.dependency_overrides[get_db_session] = get_test_db

        with TestClient(app) as client:
            yield client


@pytest.fixture
def test_client_no_ml(test_db):
    """Create a test client without ML model."""
    from main import create_app

    app = create_app()

    # Override database dependency
    def get_test_db():
        return test_db

    # Mock the categorizer to raise exception (no model available)
    def mock_get_categorizer_fail(db):
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="No trained ML model found")

    with patch("api.ml.get_categorizer", side_effect=mock_get_categorizer_fail):
        from api.dependencies import get_db_session

        app.dependency_overrides[get_db_session] = get_test_db

        with TestClient(app) as client:
            yield client


def create_test_csv() -> io.BytesIO:
    """Create a test CSV file."""
    csv_content = """date,name,purpose,amount,currency
2024-01-15,Supermarket ABC,Weekly shopping,-85.50,EUR
2024-01-16,Restaurant XYZ,Dinner,-45.00,EUR
2024-01-17,Coffee Shop,Morning coffee,-4.50,EUR
"""
    return io.BytesIO(csv_content.encode())


def test_upload_with_ml_predictions(test_client_with_ml, test_db):
    """Test CSV upload with automatic ML predictions."""
    csv_file = create_test_csv()

    response = test_client_with_ml.post("/api/upload/csv", files={"file": ("test.csv", csv_file, "text/csv")})

    if response.status_code != 200:
        print(f"Error response: {response.status_code} - {response.json()}")
    assert response.status_code == 200
    data = response.json()

    # Should have processed 3 transactions
    assert data["rows_processed"] == 3
    assert data["transactions_imported"] == 3
    assert data["duplicates_skipped"] == 0

    # Should have made ML predictions
    assert data["predictions_made"] == 3

    # Verify predictions were saved to database
    transactions = test_db.query(TransactionORM).all()
    assert len(transactions) == 3

    # Check that all transactions have predictions
    for txn in transactions:
        assert txn.predicted_category_id is not None
        assert txn.confidence_score is not None
        assert txn.confidence_score > 0

    # Check specific predictions
    restaurant_txn = test_db.query(TransactionORM).filter(TransactionORM.name.contains("Restaurant")).first()
    assert restaurant_txn.predicted_category_id == 3  # Dining
    assert restaurant_txn.confidence_score == 0.9

    supermarket_txn = test_db.query(TransactionORM).filter(TransactionORM.name.contains("Supermarket")).first()
    assert supermarket_txn.predicted_category_id == 1  # Groceries
    assert supermarket_txn.confidence_score == 0.8


def test_upload_without_ml_model(test_client_no_ml, test_db):
    """Test CSV upload when no ML model is available."""
    csv_file = create_test_csv()

    response = test_client_no_ml.post("/api/upload/csv", files={"file": ("test.csv", csv_file, "text/csv")})

    assert response.status_code == 200
    data = response.json()

    # Should still process transactions successfully
    assert data["rows_processed"] == 3
    assert data["transactions_imported"] == 3
    assert data["duplicates_skipped"] == 0

    # Should not have made predictions (ML failed gracefully)
    assert data["predictions_made"] == 0

    # Verify transactions were saved without predictions
    transactions = test_db.query(TransactionORM).all()
    assert len(transactions) == 3

    # Check that transactions don't have predictions
    for txn in transactions:
        assert txn.predicted_category_id is None
        assert txn.confidence_score is None


def test_upload_duplicate_transactions(test_client_with_ml, test_db):
    """Test upload with duplicate transactions."""
    # First upload
    csv_file1 = create_test_csv()
    response1 = test_client_with_ml.post("/api/upload/csv", files={"file": ("test1.csv", csv_file1, "text/csv")})

    assert response1.status_code == 200
    data1 = response1.json()
    assert data1["transactions_imported"] == 3
    assert data1["predictions_made"] == 3

    # Second upload with same transactions
    csv_file2 = create_test_csv()
    response2 = test_client_with_ml.post("/api/upload/csv", files={"file": ("test2.csv", csv_file2, "text/csv")})

    assert response2.status_code == 200
    data2 = response2.json()
    assert data2["transactions_imported"] == 0  # All duplicates
    assert data2["duplicates_skipped"] == 3
    assert data2["predictions_made"] == 0  # No new transactions to predict

    # Should still have only 3 transactions in database
    transaction_count = test_db.query(TransactionORM).count()
    assert transaction_count == 3


def test_upload_preview_includes_predictions(test_client_with_ml):
    """Test that upload preview includes prediction information."""
    csv_file = create_test_csv()

    # Upload file
    response = test_client_with_ml.post("/api/upload/csv", files={"file": ("test.csv", csv_file, "text/csv")})

    assert response.status_code == 200
    upload_id = response.json()["upload_id"]

    # Get preview
    preview_response = test_client_with_ml.get(f"/api/upload/preview/{upload_id}")

    assert preview_response.status_code == 200
    preview_data = preview_response.json()

    assert "summary" in preview_data
    assert "predictions_made" in preview_data["summary"]
    assert preview_data["summary"]["predictions_made"] == 3


def test_upload_confirm_includes_predictions(test_client_with_ml):
    """Test that upload confirmation includes prediction information."""
    csv_file = create_test_csv()

    # Upload file
    response = test_client_with_ml.post("/api/upload/csv", files={"file": ("test.csv", csv_file, "text/csv")})

    assert response.status_code == 200
    upload_id = response.json()["upload_id"]

    # Confirm upload
    confirm_response = test_client_with_ml.post(f"/api/upload/confirm/{upload_id}")

    assert confirm_response.status_code == 200
    confirm_data = confirm_response.json()

    assert "summary" in confirm_data
    assert "predictions_made" in confirm_data["summary"]
    assert confirm_data["summary"]["predictions_made"] == 3


if __name__ == "__main__":
    pytest.main([__file__])
