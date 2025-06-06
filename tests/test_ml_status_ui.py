"""Tests for ML status UI alerts and functionality."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from main import app
from src.fafycat.core.database import TransactionORM, CategoryORM
from src.fafycat.core.models import TransactionInput
from src.fafycat.data.csv_processor import CSVProcessor
from datetime import date


class TestMLStatusAPI:
    """Test ML status API endpoint."""

    def test_ml_status_no_model_insufficient_data(self, test_client, db_session):
        """Test ML status when no model exists and insufficient training data."""
        # Clear any existing transactions
        db_session.query(TransactionORM).delete()
        db_session.commit()

        response = test_client.get("/api/ml/status")
        assert response.status_code == 200

        status = response.json()
        assert status["model_loaded"] is False
        assert status["can_predict"] is False
        assert status["training_ready"] is False
        assert status["reviewed_transactions"] == 0
        assert status["min_training_samples"] == 50
        assert status["status"] == "Not enough training data"

    def test_ml_status_no_model_sufficient_data(self, test_client, db_session):
        """Test ML status when no model exists but sufficient training data."""
        # Clear existing data
        db_session.query(TransactionORM).delete()
        db_session.query(CategoryORM).delete()
        db_session.commit()

        # Create categories first
        categories = ["groceries", "restaurants", "utilities"]
        for cat_name in categories:
            category = CategoryORM(name=cat_name, type="spending")
            db_session.add(category)
        db_session.commit()

        # Create 60 reviewed transactions with categories
        processor = CSVProcessor(db_session)
        transactions = []

        for i in range(60):
            category = categories[i % len(categories)]
            transaction = TransactionInput(
                date=date(2024, 1, (i % 28) + 1),
                name=f"Test Merchant {i}",
                purpose=f"Test transaction {i}",
                amount=-50.0,
                category=category,
            )
            transactions.append(transaction)

        processor.save_transactions(transactions, "test_sufficient")

        response = test_client.get("/api/ml/status")
        assert response.status_code == 200

        status = response.json()
        assert status["model_loaded"] is False
        assert status["can_predict"] is False
        assert status["training_ready"] is True
        assert status["reviewed_transactions"] == 60
        assert status["status"] == "No model found - ready to train"

    @patch("api.ml.get_categorizer")
    def test_ml_status_model_loaded(self, mock_get_categorizer, test_client, db_session):
        """Test ML status when model is loaded and working."""
        # Mock a working categorizer
        mock_categorizer = MagicMock()
        mock_categorizer.model_version = "test_v1"
        mock_categorizer.is_trained = True
        mock_categorizer.classes_ = ["groceries", "restaurants", "utilities"]
        mock_get_categorizer.return_value = mock_categorizer

        # Also need to patch the model file existence check
        with patch("pathlib.Path.exists", return_value=True):
            response = test_client.get("/api/ml/status")

        assert response.status_code == 200
        status = response.json()
        assert status["model_loaded"] is True
        assert status["can_predict"] is True
        assert status["status"] == "Model loaded and ready"
        assert status["classes_count"] == 3


class TestMLStatusAlerts:
    """Test ML status alert generation in UI pages."""

    def test_import_page_model_status_alert_no_data(self, test_client, db_session):
        """Test import page shows correct alert when no training data."""
        # Clear existing transactions
        db_session.query(TransactionORM).delete()
        db_session.commit()

        response = test_client.get("/")
        assert response.status_code == 200

        html = response.text
        # Should show building training data message
        assert "Building training data" in html
        assert "bg-blue-50" in html  # Blue alert
        assert "need 50+" in html

    def test_import_page_model_status_alert_ready_to_train(self, test_client, db_session):
        """Test import page shows correct alert when ready to train."""
        # Create sufficient training data
        db_session.query(TransactionORM).delete()
        db_session.commit()

        processor = CSVProcessor(db_session)
        transactions = []
        for i in range(60):
            transaction = TransactionInput(
                date=date(2024, 1, (i % 28) + 1),
                name=f"Test Merchant {i}",
                purpose=f"Test purpose {i}",
                amount=-50.0,
                category="groceries",
            )
            transactions.append(transaction)

        processor.save_transactions(transactions, "test_ready_to_train")

        response = test_client.get("/")
        assert response.status_code == 200

        html = response.text
        # Should show ready to train message
        assert "No ML model trained yet" in html
        assert "bg-yellow-50" in html  # Yellow alert
        assert "ready for training" in html

    @patch("api.ml.get_categorizer")
    @patch("pathlib.Path.exists")
    def test_import_page_model_status_alert_model_ready(self, mock_exists, mock_get_categorizer, test_client):
        """Test import page shows success when model is working."""
        mock_exists.return_value = True
        mock_categorizer = MagicMock()
        mock_categorizer.model_version = "test_v1"
        mock_categorizer.is_trained = True
        mock_categorizer.classes_ = ["groceries"]
        mock_get_categorizer.return_value = mock_categorizer

        response = test_client.get("/")
        assert response.status_code == 200

        html = response.text
        # Should show model ready message
        assert "ML model ready for predictions" in html
        assert "bg-green-50" in html  # Green alert

    def test_review_page_model_status_alert_ready_to_train(self, test_client, db_session):
        """Test review page shows correct alert when ready to train."""
        # Create sufficient training data
        db_session.query(TransactionORM).delete()
        db_session.commit()

        processor = CSVProcessor(db_session)
        transactions = []
        for i in range(60):
            transaction = TransactionInput(
                date=date(2024, 1, (i % 28) + 1),
                name=f"Test Merchant {i}",
                purpose=f"Test purpose {i}",
                amount=-50.0,
                category="groceries",
            )
            transactions.append(transaction)

        processor.save_transactions(transactions, "test_ready_review")

        response = test_client.get("/review")
        assert response.status_code == 200

        html = response.text
        # Should show ready to train alert on review page
        assert "Ready to train ML model" in html
        assert "bg-blue-50" in html  # Blue alert
        assert "Train Model Now" in html


class TestMLStatusIntegration:
    """Integration tests for ML status functionality."""

    def test_status_api_performance(self, test_client, db_session):
        """Test that ML status API responds quickly even with many transactions."""
        # Create many transactions
        db_session.query(TransactionORM).delete()
        db_session.commit()

        processor = CSVProcessor(db_session)
        transactions = []
        for i in range(1000):  # Large dataset
            transaction = TransactionInput(
                date=date(2024, 1, (i % 28) + 1),
                name=f"Merchant {i}",
                purpose=f"Transaction {i}",
                amount=-25.0,
                category="groceries" if i < 500 else None,  # Half reviewed
            )
            transactions.append(transaction)

        processor.save_transactions(transactions, "test_performance")

        import time

        start_time = time.time()
        response = test_client.get("/api/ml/status")
        end_time = time.time()

        assert response.status_code == 200
        assert (end_time - start_time) < 1.0  # Should respond within 1 second

        status = response.json()
        assert status["reviewed_transactions"] == 500
        assert status["unpredicted_transactions"] == 1000  # All are unpredicted

    def test_alert_error_handling(self, test_client):
        """Test that UI gracefully handles API errors."""
        # This tests the error handling in the alert functions
        with patch("httpx.get", side_effect=Exception("Connection error")):
            response = test_client.get("/")
            assert response.status_code == 200
            # Should not crash, should fail silently

            response = test_client.get("/review")
            assert response.status_code == 200
            # Should not crash, should fail silently
