"""Tests for auto-prediction after training completion."""

from datetime import date

from sqlalchemy import text

import fafycat.api.ml as ml_api
from fafycat.api.ml_training_job import create_training_job, get_current_job, set_job_running
from fafycat.core.database import CategoryORM, TransactionORM
from fafycat.core.models import TransactionInput
from fafycat.data.csv_processor import CSVProcessor

MERCHANTS = {"groceries": "REWE Markt", "restaurants": "Pizzeria Roma", "utilities": "Stadtwerke Berlin"}


def seed_training_and_pending(db_session) -> None:
    """60 reviewed rows to train on and 10 pending rows without a prediction."""
    db_session.execute(text("DELETE FROM transactions"))
    db_session.execute(text("DELETE FROM categories"))
    for name in MERCHANTS:
        db_session.add(CategoryORM(name=name, type="spending"))
    db_session.commit()

    processor = CSVProcessor(db_session)
    processor.save_transactions(
        [
            TransactionInput(
                date=date(2024, 1, (i % 28) + 1),
                name=merchant,
                purpose=f"{category} order {i}",
                amount=-50.0 - i,
                category=category,
            )
            for i in range(20)
            for category, merchant in MERCHANTS.items()
        ],
        "test_training",
    )
    processor.save_transactions(
        [
            TransactionInput(
                date=date(2024, 2, (i % 28) + 1),
                name=f"Pending Merchant {i}",
                purpose=f"Pending transaction {i}",
                amount=-25.0,
            )
            for i in range(10)
        ],
        "test_pending",
    )


def run_training_job() -> dict:
    """Run one training job synchronously and return its final state."""
    create_training_job()
    set_job_running()
    ml_api._run_training_sync()
    job = get_current_job()
    assert job is not None
    return job.to_dict()


class TestAutoPredictPostTraining:
    """Test automatic prediction after training completion."""

    def test_training_job_predicts_every_unpredicted_transaction(self, db_session, monkeypatch):
        seed_training_and_pending(db_session)
        already_predicted = db_session.query(TransactionORM).filter(TransactionORM.name == "Pending Merchant 0").one()
        already_predicted.predicted_category_id = db_session.query(CategoryORM).first().id
        already_predicted.confidence_score = 0.42
        db_session.commit()
        # Small batches, so the job has to keep going until nothing is left.
        monkeypatch.setattr(ml_api, "RETRAIN_PREDICT_BATCH_SIZE", 4)

        job = run_training_job()

        assert job["status"] == "completed"
        result = job["result"]
        assert result["auto_accepted"] + result["needs_review"] == 9
        assert result["already_reviewed"] == 60
        assert result["predictions_made"] == 69
        assert result["prediction_error"] is None
        db_session.expire_all()
        assert db_session.query(TransactionORM).filter(TransactionORM.predicted_category_id.is_(None)).count() == 0
        # Rows that already had a prediction are left for an explicit re-predict.
        db_session.refresh(already_predicted)
        assert already_predicted.confidence_score == 0.42

    def test_a_prediction_failure_does_not_fail_the_training(self, db_session, tmp_data_dir, monkeypatch):
        seed_training_and_pending(db_session)

        def broken_predict(*args, **kwargs):
            raise RuntimeError("prediction exploded")

        monkeypatch.setattr(ml_api, "predict_unpredicted", broken_predict)

        job = run_training_job()

        assert job["status"] == "completed"
        assert (tmp_data_dir / "models" / "ensemble_categorizer.pkl").exists()
        assert job["result"]["predictions_made"] == 0
        assert "prediction exploded" in job["result"]["prediction_error"]

    def test_batch_unpredicted_endpoint_works(self, test_client, db_session):
        """Test that batch unpredicted endpoint works correctly."""
        # This test ensures the endpoint exists and works
        # In real usage, this would be called after training
        response = test_client.post("/api/ml/predict/batch-unpredicted")

        # Should return proper response even if no model exists
        assert response.status_code in [200, 503]  # 503 if no model, 200 if working

    def test_settings_page_includes_auto_predict_messaging(self, test_client, db_session):
        """Test that settings page includes messaging about auto-prediction."""
        # Ensure we have at least one category so we get the full settings page
        category = CategoryORM(name="test_category", type="spending")
        db_session.add(category)
        db_session.commit()

        response = test_client.get("/settings")
        assert response.status_code == 200

        html = response.text
        # Check that the settings page contains ML training functionality
        assert "ML Model Training" in html or "Train ML Model" in html
        # Check that the page includes the necessary API endpoints for training
        assert "/api/ml/retrain" in html
        # Check that the page includes prediction functionality
        assert "predict" in html.lower()

    def test_training_workflow_user_experience(self, test_client, db_session):
        """Test the complete training workflow user experience."""
        # Ensure we have at least one category so we get the full settings page
        category = CategoryORM(name="test_category", type="spending")
        db_session.add(category)
        db_session.commit()

        response = test_client.get("/settings")
        assert response.status_code == 200

        html = response.text

        # Check that the page includes ML training workflow elements
        assert "function trainModel()" in html or "trainModel" in html
        # Check that the page includes prediction functionality
        assert "/api/ml/retrain" in html
        # Check that the page includes necessary JavaScript for workflows
        assert "fetch(" in html and "/api/ml/" in html

    def test_error_handling_in_auto_prediction(self, test_client, db_session):
        """Test that auto-prediction errors are handled gracefully."""
        # Ensure we have at least one category so we get the full settings page
        category = CategoryORM(name="test_category", type="spending")
        db_session.add(category)
        db_session.commit()

        response = test_client.get("/settings")
        assert response.status_code == 200

        html = response.text

        # Check that the page includes error handling for training/prediction
        assert "catch(" in html or "error" in html.lower()
        # Check that the page includes ML functionality
        assert "/api/ml/" in html
        # Check that training functionality is present
        assert "train" in html.lower()

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
