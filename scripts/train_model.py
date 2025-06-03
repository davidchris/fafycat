#!/usr/bin/env python3
"""Train the ML categorization model."""

import os
import sys
from pathlib import Path

# Set production environment to use the correct database
os.environ["FAFYCAT_DB_URL"] = "sqlite:///data/fafycat_prod.db"
os.environ["FAFYCAT_ENV"] = "production"

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fafycat.core.config import AppConfig
from fafycat.core.database import DatabaseManager
from fafycat.ml.categorizer import TransactionCategorizer


def main() -> None:
    """Train and save the model."""
    config = AppConfig()
    config.ensure_dirs()

    db_manager = DatabaseManager(config)

    with db_manager.get_session() as session:
        print("Initializing categorizer...")
        categorizer = TransactionCategorizer(session, config.ml)

        try:
            print("Starting training...")
            metrics = categorizer.train()

            print("\nTraining Results:")
            print(f"Overall Accuracy: {metrics.accuracy:.3f}")
            print("\nPer-category Precision:")
            for category, precision in metrics.precision_per_category.items():
                print(f"  {category}: {precision:.3f}")

            print("\nTop Feature Importance:")
            sorted_features = sorted(metrics.feature_importance.items(), key=lambda x: x[1], reverse=True)[:10]

            for feature, importance in sorted_features:
                print(f"  {feature}: {importance:.3f}")

            # Save model
            model_path = config.ml.model_dir / "categorizer.pkl"
            categorizer.save_model(model_path)
            print(f"\nModel saved to: {model_path}")

        except ValueError as e:
            print(f"Training failed: {e}")
            print("Make sure you have enough transactions with confirmed categories.")
            print("Try importing more data or manually categorizing existing transactions.")


if __name__ == "__main__":
    main()
