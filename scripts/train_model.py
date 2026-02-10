#!/usr/bin/env python3
"""Train the ML categorization model."""

import os
import sys
from pathlib import Path

# Set production environment to use the correct database
os.environ["FAFYCAT_DB_URL"] = "sqlite:///data/fafycat_prod.db"
os.environ["FAFYCAT_ENV"] = "production"

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.fafycat.core.config import AppConfig
from src.fafycat.core.database import DatabaseManager
from src.fafycat.ml.categorizer import TransactionCategorizer
from src.fafycat.ml.ensemble_categorizer import EnsembleCategorizer


def main() -> None:
    """Train and save the model."""
    config = AppConfig()
    config.ensure_dirs()

    db_manager = DatabaseManager(config)

    with db_manager.get_session() as session:
        try:
            # Choose between ensemble and single model based on config
            if config.ml.use_ensemble:
                print("Initializing ensemble categorizer...")
                ensemble_categorizer = EnsembleCategorizer(session, config.ml)
                model_filename = "ensemble_categorizer.pkl"

                print("Starting ensemble training with validation optimization...")
                cv_results = ensemble_categorizer.train_with_validation_optimization()

                print("\nEnsemble Training Results:")
                print(f"Validation Accuracy: {cv_results['validation_accuracy']:.3f}")
                print(
                    f"Optimal Weights: LightGBM={cv_results['best_weights']['lgbm']:.1f}, "
                    f"NB={cv_results['best_weights']['nb']:.1f}"
                )
                print(f"Training samples: {cv_results['n_training_samples']}")
                print(f"Validation samples: {cv_results['n_validation_samples']}")

                # Save model
                model_path = config.ml.model_dir / model_filename
                ensemble_categorizer.save_model(model_path)
            else:
                print("Initializing single categorizer...")
                single_categorizer = TransactionCategorizer(session, config.ml)
                model_filename = "categorizer.pkl"

                print("Starting single model training...")
                metrics = single_categorizer.train()

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
                single_categorizer.save_model(model_path)

            print(f"\nModel saved to: {model_path}")

        except ValueError as e:
            print(f"Training failed: {e}")
            print("Make sure you have enough transactions with confirmed categories.")
            print("Try importing more data or manually categorizing existing transactions.")


if __name__ == "__main__":
    main()
