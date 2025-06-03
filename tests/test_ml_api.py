"""Tests for ML API endpoints."""

import os
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from fafycat.core.config import AppConfig, MLConfig
from fafycat.core.database import Base, CategoryORM, TransactionORM
from fafycat.core.models import TransactionInput, TransactionPrediction


@pytest.fixture
def test_db():
    """Create a test database."""
    # Use in-memory SQLite for testing
    engine = create_engine("sqlite:///:memory:", echo=False)
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
    
    # Add test transactions
    transactions = [
        TransactionORM(
            id="txn1",
            date=date(2024, 1, 15),
            value_date=date(2024, 1, 15),
            name="Supermarket ABC",
            purpose="Weekly shopping",
            amount=-85.50,
            currency="EUR",
            category_id=1,  # Groceries
            predicted_category_id=None,
            confidence_score=None,
            is_reviewed=True,
            imported_at=datetime.now(),
            import_batch="batch1",
        ),
        TransactionORM(
            id="txn2",
            date=date(2024, 1, 16),
            value_date=date(2024, 1, 16),
            name="Restaurant XYZ",
            purpose="Dinner",
            amount=-45.00,
            currency="EUR",
            category_id=None,  # No category yet
            predicted_category_id=None,
            confidence_score=None,
            is_reviewed=False,
            imported_at=datetime.now(),
            import_batch="batch1",
        ),
    ]
    
    for txn in transactions:
        session.add(txn)
    
    session.commit()
    
    yield session
    session.close()


@pytest.fixture
def mock_categorizer():
    """Create a mock categorizer for testing."""
    categorizer = MagicMock()
    categorizer.is_trained = True
    categorizer.model_version = "test_1.0"
    categorizer.classes_ = [1, 2, 3]
    
    # Mock prediction
    def mock_predict(transactions):
        predictions = []
        for txn in transactions:
            if "restaurant" in txn.name.lower() or "dining" in txn.purpose.lower():
                pred = TransactionPrediction(
                    transaction_id=txn.generate_id(),
                    predicted_category_id=3,  # Dining
                    confidence_score=0.85,
                    feature_contributions={"merchant_name": 0.7, "amount_range": 0.3},
                )
            else:
                pred = TransactionPrediction(
                    transaction_id=txn.generate_id(),
                    predicted_category_id=1,  # Groceries
                    confidence_score=0.75,
                    feature_contributions={"merchant_name": 0.8, "amount_range": 0.2},
                )
            predictions.append(pred)
        return predictions
    
    categorizer.predict_with_confidence = mock_predict
    
    def mock_explanation(txn):
        pred = mock_predict([txn])[0]
        return {
            "prediction": pred,
            "category_name": "dining" if pred.predicted_category_id == 3 else "groceries",
            "confidence_level": "High" if pred.confidence_score > 0.8 else "Medium",
            "merchant_suggestions": [],
        }
    
    categorizer.get_prediction_explanation = mock_explanation
    categorizer._get_confidence_level = lambda conf: "High" if conf > 0.8 else "Medium"
    
    return categorizer


@pytest.fixture
def test_client(test_db, mock_categorizer):
    """Create a test client with mocked dependencies."""
    from main import create_app
    
    app = create_app()
    
    # Override database dependency
    def get_test_db():
        return test_db
    
    # Override categorizer dependency
    def get_test_categorizer():
        return mock_categorizer
    
    # Patch dependencies
    from api.dependencies import get_db_session
    from api.ml import get_categorizer
    
    app.dependency_overrides[get_db_session] = get_test_db
    app.dependency_overrides[get_categorizer] = get_test_categorizer
    
    with TestClient(app) as client:
        yield client


def test_ml_status_endpoint(test_client):
    """Test ML status endpoint."""
    response = test_client.get("/api/ml/status")
    assert response.status_code == 200
    
    data = response.json()
    assert "model_loaded" in data
    assert "can_predict" in data
    assert "status" in data


def test_predict_single_transaction(test_client):
    """Test single transaction prediction."""
    request_data = {
        "date": "2024-01-20",
        "name": "Restaurant ABC",
        "purpose": "Lunch",
        "amount": -25.50,
        "currency": "EUR",
    }
    
    response = test_client.post("/api/ml/predict", json=request_data)
    assert response.status_code == 200
    
    data = response.json()
    assert "predicted_category_id" in data
    assert "predicted_category_name" in data
    assert "confidence_score" in data
    assert "feature_contributions" in data
    assert "confidence_level" in data
    
    # Should predict dining category for restaurant
    assert data["predicted_category_id"] == 3
    assert data["predicted_category_name"] == "dining"
    assert data["confidence_score"] > 0.8
    assert data["confidence_level"] == "High"


def test_predict_bulk_transactions(test_client):
    """Test bulk transaction prediction."""
    request_data = {
        "transactions": [
            {
                "date": "2024-01-20",
                "name": "Restaurant ABC",
                "purpose": "Lunch",
                "amount": -25.50,
                "currency": "EUR",
            },
            {
                "date": "2024-01-21",
                "name": "Supermarket XYZ",
                "purpose": "Groceries",
                "amount": -78.30,
                "currency": "EUR",
            },
        ]
    }
    
    response = test_client.post("/api/ml/predict/bulk", json=request_data)
    assert response.status_code == 200
    
    data = response.json()
    assert "predictions" in data
    assert "total_processed" in data
    assert "processing_time_ms" in data
    
    assert len(data["predictions"]) == 2
    assert data["total_processed"] == 2
    assert data["processing_time_ms"] > 0
    
    # Check individual predictions
    predictions = data["predictions"]
    
    # Restaurant should be dining
    assert predictions[0]["predicted_category_id"] == 3
    assert predictions[0]["predicted_category_name"] == "dining"
    
    # Supermarket should be groceries
    assert predictions[1]["predicted_category_id"] == 1
    assert predictions[1]["predicted_category_name"] == "groceries"


def test_predict_batch_unpredicted(test_client, test_db):
    """Test batch prediction of unpredicted transactions."""
    response = test_client.post("/api/ml/predict/batch-unpredicted")
    assert response.status_code == 200
    
    data = response.json()
    assert "status" in data
    assert "predictions_made" in data
    
    # Should have made predictions for the unpredicted transaction
    assert data["predictions_made"] >= 1
    
    # Verify that predictions were saved to database
    unpredicted_count = test_db.query(TransactionORM).filter(
        TransactionORM.predicted_category_id.is_(None)
    ).count()
    assert unpredicted_count == 0  # All should now have predictions


def test_predict_invalid_request(test_client):
    """Test prediction with invalid request data."""
    # Missing required fields
    request_data = {
        "name": "Restaurant ABC",
        # Missing date and amount
    }
    
    response = test_client.post("/api/ml/predict", json=request_data)
    assert response.status_code == 422  # Validation error


def test_predict_without_model():
    """Test prediction when no model is available."""
    from main import create_app
    
    app = create_app()
    
    # Don't override the categorizer dependency so it tries to load real model
    with TestClient(app) as client:
        response = client.get("/api/ml/status")
        # Should return that no model is found
        data = response.json()
        assert data["model_loaded"] is False
        assert data["can_predict"] is False


@patch("api.ml.get_categorizer")
def test_prediction_error_handling(mock_get_categorizer, test_client):
    """Test error handling when prediction fails."""
    # Make the categorizer raise an exception
    mock_get_categorizer.side_effect = Exception("Model error")
    
    request_data = {
        "date": "2024-01-20",
        "name": "Restaurant ABC",
        "purpose": "Lunch",
        "amount": -25.50,
        "currency": "EUR",
    }
    
    response = test_client.post("/api/ml/predict", json=request_data)
    assert response.status_code == 500
    assert "Prediction failed" in response.json()["detail"]


if __name__ == "__main__":
    pytest.main([__file__])