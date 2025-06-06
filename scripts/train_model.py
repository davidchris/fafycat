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
from fafycat.ml.ensemble_categorizer import EnsembleCategorizer


def main() -> None:
    """Train and save the model."""
    config = AppConfig()
    config.ensure_dirs()

    db_manager = DatabaseManager(config)

    with db_manager.get_session() as session:
        # Choose between ensemble and single model based on config
        if config.ml.use_ensemble:
            print("Initializing ensemble categorizer...")
            categorizer = EnsembleCategorizer(session, config.ml)
            model_filename = "ensemble_categorizer.pkl"
        else:
            print("Initializing single categorizer...")
            categorizer = TransactionCategorizer(session, config.ml)
            model_filename = "categorizer.pkl"

        try:
            if config.ml.use_ensemble:
                print("Starting ensemble training with validation optimization...")
                cv_results = categorizer.train_with_validation_optimization()

                print("\nEnsemble Training Results:")
                print(f"Validation Accuracy: {cv_results['validation_accuracy']:.3f}")
                print(f"Optimal Weights: LightGBM={cv_results['best_weights']['lgbm']:.1f}, NB={cv_results['best_weights']['nb']:.1f}")
                print(f"Training samples: {cv_results['n_training_samples']}")
                print(f"Validation samples: {cv_results['n_validation_samples']}")
            else:
                print("Starting single model training...")
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
            model_path = config.ml.model_dir / model_filename
            categorizer.save_model(model_path)
            print(f"\nModel saved to: {model_path}")

        except ValueError as e:
            print(f"Training failed: {e}")
            print("Make sure you have enough transactions with confirmed categories.")
            print("Try importing more data or manually categorizing existing transactions.")


if __name__ == "__main__":
    main()
