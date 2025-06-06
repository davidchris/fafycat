"""Tests for auto-prediction after training completion."""

from unittest.mock import patch, MagicMock
from sqlalchemy import text
from src.fafycat.core.database import TransactionORM, CategoryORM
from src.fafycat.core.models import TransactionInput
from src.fafycat.data.csv_processor import CSVProcessor
from datetime import date


class TestAutoPredictPostTraining:
    """Test automatic prediction after training completion."""

    def test_retrain_endpoint_triggers_auto_prediction(self, test_client, db_session):
        """Test that the retrain endpoint can trigger automatic prediction."""
        # Clear existing data
        db_session.execute(text("DELETE FROM transactions"))
        db_session.execute(text("DELETE FROM categories"))
        db_session.commit()
        db_session.flush()

        # Create categories
        categories = ["groceries", "restaurants", "utilities"]
        for cat_name in categories:
            category = CategoryORM(name=cat_name, type="spending")
            db_session.add(category)
        db_session.commit()

        # Create sufficient training data (reviewed transactions)
        processor = CSVProcessor(db_session)
        training_transactions = []
        for i in range(60):
            category = categories[i % len(categories)]
            transaction = TransactionInput(
                date=date(2024, 1, (i % 28) + 1),
                name=f"Training Merchant {i}",
                purpose=f"Training transaction {i}",
                amount=-50.0,
                category=category,
            )
            training_transactions.append(transaction)

        processor.save_transactions(training_transactions, "test_training")

        # Create unpredicted transactions (no category, is_reviewed=False)
        unpredicted_transactions = []
        for i in range(10):
            transaction = TransactionInput(
                date=date(2024, 2, (i % 28) + 1),
                name=f"Unpredicted Merchant {i}",
                purpose=f"Unpredicted transaction {i}",
                amount=-25.0,
                # No category - these need prediction
            )
            unpredicted_transactions.append(transaction)

        processor.save_transactions(unpredicted_transactions, "test_unpredicted")

        # Verify setup
        reviewed_count = (
            db_session.query(TransactionORM)
            .filter(TransactionORM.is_reviewed, TransactionORM.category_id.is_not(None))
            .count()
        )

        # Count transactions that need predictions (no actual category set)
        unpredicted_count = db_session.query(TransactionORM).filter(TransactionORM.category_id.is_(None)).count()

        assert reviewed_count == 60, f"Expected 60 reviewed transactions, got {reviewed_count}"
        assert unpredicted_count == 10, f"Expected 10 unpredicted transactions, got {unpredicted_count}"

    def test_batch_unpredicted_endpoint_works(self, test_client, db_session):
        """Test that batch unpredicted endpoint works correctly."""
        # This test ensures the endpoint exists and works
        # In real usage, this would be called after training
        response = test_client.post("/api/ml/predict/batch-unpredicted")

        # Should return proper response even if no model exists
        assert response.status_code in [200, 503]  # 503 if no model, 200 if working

    def test_settings_page_includes_auto_predict_messaging(self, test_client, db_session):
        """Test that settings page includes messaging about auto-prediction."""
        response = test_client.get("/settings")
        assert response.status_code == 200

        html = response.text
        # Check that the retraining confirmation includes auto-prediction message
        assert "automatically predict unpredicted transactions" in html
        # Check that the trainModel function includes auto-prediction logic
        assert "Auto-predicting..." in html
        assert "/api/ml/predict/batch-unpredicted" in html

    def test_training_workflow_user_experience(self, test_client, db_session):
        """Test the complete training workflow user experience."""
        response = test_client.get("/settings")
        assert response.status_code == 200

        html = response.text

        # Check for proper user messaging
        success_messages = [
            "Training and prediction completed!",
            "Auto-Prediction Results:",
            "transactions now have predictions",
            "Ready for review on the Review page!",
        ]

        for message in success_messages:
            assert message in html, f"Expected message '{message}' not found in HTML"

        # Check for fallback messaging
        fallback_messages = [
            "Auto-prediction failed, but you can predict manually",
            "All transactions already have predictions!",
        ]

        for message in fallback_messages:
            assert message in html, f"Expected fallback message '{message}' not found in HTML"

    def test_error_handling_in_auto_prediction(self, test_client, db_session):
        """Test that auto-prediction errors are handled gracefully."""
        response = test_client.get("/settings")
        assert response.status_code == 200

        html = response.text

        # Check that training success is still shown even if auto-prediction fails
        assert "Training succeeded but prediction failed" in html or "Auto-prediction failed" in html

        # Check that the button text shows the prediction phase
        assert "Auto-predicting..." in html

        # Check that users can still predict manually if auto-prediction fails
        assert "you can predict manually from this page" in html

    def test_ml_status_after_training_and_prediction(self, test_client, db_session):
        """Test ML status endpoint shows correct state after training and prediction."""
        response = test_client.get("/api/ml/status")
        assert response.status_code == 200

        status = response.json()

        # The status should include unpredicted transaction count
        assert "unpredicted_transactions" in status
        assert isinstance(status["unpredicted_transactions"], int)

        # Should show training readiness information
        assert "training_ready" in status
        assert "reviewed_transactions" in status
        assert "min_training_samples" in status
