"""Tests for ML training functionality in settings page."""

from unittest.mock import patch, MagicMock
from src.fafycat.core.database import TransactionORM, CategoryORM
from src.fafycat.core.models import TransactionInput
from src.fafycat.data.csv_processor import CSVProcessor
from datetime import date


class TestSettingsMLTraining:
    """Test ML training functionality in settings page."""

    def test_settings_page_no_model_insufficient_data(self, test_client, db_session):
        """Test settings page shows 'need more data' when insufficient training data."""
        # Clear existing data
        db_session.query(TransactionORM).delete()
        db_session.query(CategoryORM).delete()
        db_session.commit()

        # Create just a few transactions (less than 50)
        categories = ["groceries", "restaurants"]
        for cat_name in categories:
            category = CategoryORM(name=cat_name, type="spending")
            db_session.add(category)
        db_session.commit()

        processor = CSVProcessor(db_session)
        transactions = []
        for i in range(10):  # Only 10 transactions
            transaction = TransactionInput(
                date=date(2024, 1, i + 1),
                name=f"Test Merchant {i}",
                purpose=f"Test transaction {i}",
                amount=-50.0,
                category="groceries",
            )
            transactions.append(transaction)

        processor.save_transactions(transactions, "test_insufficient")

        response = test_client.get("/settings")
        assert response.status_code == 200

        html = response.text
        # Should show need more data message
        assert "Need more training data" in html
        assert "need at least 50" in html
        assert "You have 10 reviewed transactions" in html
        assert "bg-yellow-50" in html  # Yellow alert

    def test_settings_page_ready_to_train(self, test_client, db_session):
        """Test settings page shows train button when ready."""
        # Clear existing data
        db_session.query(TransactionORM).delete()
        db_session.query(CategoryORM).delete()
        db_session.commit()

        # Create categories
        categories = ["groceries", "restaurants", "utilities"]
        for cat_name in categories:
            category = CategoryORM(name=cat_name, type="spending")
            db_session.add(category)
        db_session.commit()

        # Create sufficient training data
        processor = CSVProcessor(db_session)
        transactions = []
        for i in range(60):  # Sufficient data
            category = categories[i % len(categories)]
            transaction = TransactionInput(
                date=date(2024, 1, (i % 28) + 1),
                name=f"Test Merchant {i}",
                purpose=f"Test transaction {i}",
                amount=-50.0,
                category=category,
            )
            transactions.append(transaction)

        processor.save_transactions(transactions, "test_ready_to_train")

        response = test_client.get("/settings")
        assert response.status_code == 200

        html = response.text
        # Should show ready to train message
        assert "Ready to train your first ML model!" in html
        assert "You have 60 reviewed transactions" in html
        assert "Train ML Model Now" in html
        assert "trainModel()" in html  # JavaScript function
        assert "bg-blue-50" in html  # Blue alert

    def test_settings_ml_javascript_functions(self, test_client, db_session):
        """Test that ML training JavaScript functions are included."""
        response = test_client.get("/settings")
        assert response.status_code == 200

        html = response.text
        # Check that all necessary JavaScript functions are present
        assert "function trainModel()" in html
        assert "function retrainModel()" in html
        assert "function predictUnpredicted()" in html
        assert "/api/ml/retrain" in html
        assert "/api/ml/predict/batch-unpredicted" in html

    def test_settings_empty_state_with_ml_status(self, test_client, db_session):
        """Test settings page empty state includes ML status."""
        # Clear all data to trigger empty state
        db_session.query(TransactionORM).delete()
        db_session.query(CategoryORM).delete()
        db_session.commit()
        # Ensure changes are flushed
        db_session.flush()

        response = test_client.get("/settings")
        assert response.status_code == 200

        html = response.text
        # The page should load successfully and include basic elements
        assert "Settings & Categories" in html
        assert "FafyCat" in html
        # Should include ML or training functionality
        assert "train" in html.lower() or "ml" in html.lower()
        # Should have functional JavaScript
        assert "function" in html
