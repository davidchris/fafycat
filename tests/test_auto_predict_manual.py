#!/usr/bin/env python3
"""Manual test for auto-prediction after training workflow."""

import os
import sys
from pathlib import Path

# Add project root to Python path for imports
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Set development environment
os.environ["FAFYCAT_DB_URL"] = "sqlite:///data/fafycat_dev.db"
os.environ["FAFYCAT_ENV"] = "development"

from fastapi.testclient import TestClient
from main import app
from src.fafycat.core.config import AppConfig
from src.fafycat.core.database import DatabaseManager, TransactionORM, CategoryORM
from src.fafycat.core.models import TransactionInput
from src.fafycat.data.csv_processor import CSVProcessor
from datetime import date


def setup_test_scenario():
    """Set up test scenario with training data and unpredicted transactions."""
    print("🧪 Setting up Auto-Prediction Test Scenario")
    print("=" * 50)

    config = AppConfig()
    config.ensure_dirs()
    db_manager = DatabaseManager(config)

    # Clear existing data
    print("🧹 Clearing existing test data...")
    with db_manager.get_session() as session:
        session.query(TransactionORM).delete()
        session.query(CategoryORM).delete()
        session.commit()

    # Remove model file if it exists
    model_path = config.ml.model_dir / "categorizer.pkl"
    if model_path.exists():
        model_path.unlink()
        print("🗑️  Removed existing model file")

    print("\n📝 Creating test scenario:")
    print("  • 60 reviewed transactions (training data)")
    print("  • 15 unpredicted transactions (need prediction)")
    print("  • 3 categories (groceries, restaurants, utilities)")

    with db_manager.get_session() as session:
        # Create categories
        categories = ["groceries", "restaurants", "utilities"]
        for cat_name in categories:
            category = CategoryORM(name=cat_name, type="spending")
            session.add(category)
        session.commit()

        processor = CSVProcessor(session)

        # Create training data (reviewed transactions with categories)
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

        # Create unpredicted transactions (no category)
        unpredicted_transactions = []
        for i in range(15):
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
            session.query(TransactionORM)
            .filter(TransactionORM.is_reviewed, TransactionORM.category_id.is_not(None))
            .count()
        )

        unpredicted_count = session.query(TransactionORM).filter(TransactionORM.predicted_category_id.is_(None)).count()

        print("\n✅ Setup complete:")
        print(f"  • Reviewed transactions: {reviewed_count}")
        print(f"  • Unpredicted transactions: {unpredicted_count}")
        print(f"  • Categories: {len(categories)}")


def test_ml_status_shows_ready_to_train():
    """Test that ML status shows ready to train."""
    print("\n🔍 Testing ML Status API")
    print("-" * 30)

    client = TestClient(app)
    response = client.get("/api/ml/status")

    if response.status_code == 200:
        status = response.json()
        print(f"Model loaded: {status.get('model_loaded', False)}")
        print(f"Training ready: {status.get('training_ready', False)}")
        print(f"Reviewed transactions: {status.get('reviewed_transactions', 0)}")
        print(f"Unpredicted transactions: {status.get('unpredicted_transactions', 0)}")

        if status.get("training_ready", False):
            print("✅ Ready to train model!")
        else:
            print("❌ Not ready to train - check data setup")

        return status
    else:
        print(f"❌ ML Status API failed: {response.status_code}")
        return None


def test_settings_page_auto_predict_ui():
    """Test that settings page shows auto-prediction UI elements."""
    print("\n🎨 Testing Settings Page Auto-Prediction UI")
    print("-" * 45)

    client = TestClient(app)
    response = client.get("/settings")

    if response.status_code == 200:
        html = response.text

        # Check for auto-prediction elements
        checks = {
            "Auto-predicting button text": "Auto-predicting..." in html,
            "Auto-prediction API endpoint": "/api/ml/predict/batch-unpredicted" in html,
            "Retrain confirmation message": "automatically predict unpredicted transactions" in html,
            "Success message for predictions": "transactions now have predictions" in html,
            "Review page redirect": "Ready for review on the Review page" in html,
            "Fallback error handling": "Auto-prediction failed" in html,
        }

        for check_name, passed in checks.items():
            status = "✅" if passed else "❌"
            print(f"  {status} {check_name}")

        all_passed = all(checks.values())
        print(f"\n{'✅' if all_passed else '❌'} Overall UI check: {'PASSED' if all_passed else 'FAILED'}")
        return all_passed
    else:
        print(f"❌ Settings page failed to load: {response.status_code}")
        return False


def test_batch_unpredicted_api():
    """Test the batch unpredicted API endpoint."""
    print("\n🔗 Testing Batch Unpredicted API")
    print("-" * 35)

    client = TestClient(app)
    response = client.post("/api/ml/predict/batch-unpredicted")

    print(f"Status Code: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        print(f"Response: {data}")
        predictions = data.get("predictions_made", 0)
        print(f"✅ API working - {predictions} predictions made")
        return True
    elif response.status_code == 503:
        print("⚠️ No model available (expected for this test)")
        return True  # This is expected before training
    else:
        print(f"❌ API error: {response.text}")
        return False


def main():
    """Run the complete auto-prediction test."""
    print("🤖 FafyCat Auto-Prediction After Training Test")
    print("=" * 55)
    print("This test verifies the complete workflow:")
    print("1. Setup training data and unpredicted transactions")
    print("2. Check ML status shows ready to train")
    print("3. Verify settings page has auto-prediction UI")
    print("4. Test batch prediction API endpoint")
    print()

    # Setup test scenario
    setup_test_scenario()

    # Test ML status
    ml_status = test_ml_status_shows_ready_to_train()

    # Test settings page UI
    ui_passed = test_settings_page_auto_predict_ui()

    # Test API endpoint
    api_passed = test_batch_unpredicted_api()

    print("\n" + "=" * 55)
    print("📋 Test Summary")
    print("=" * 55)

    if ml_status and ml_status.get("training_ready"):
        print("✅ Data setup: Ready for training")
    else:
        print("❌ Data setup: Not ready for training")

    print(f"{'✅' if ui_passed else '❌'} UI elements: Auto-prediction interface")
    print(f"{'✅' if api_passed else '❌'} API endpoint: Batch prediction")

    print("\n🚀 Next Steps:")
    print("1. Start the dev server: uv run python run_dev.py")
    print("2. Go to Settings page: http://localhost:8000/settings")
    print("3. Click 'Train ML Model Now' button")
    print("4. Observe auto-prediction workflow in action!")
    print("5. Check Review page for newly predicted transactions")


if __name__ == "__main__":
    main()
