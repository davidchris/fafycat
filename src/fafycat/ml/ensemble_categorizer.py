"""Ensemble categorizer combining LightGBM and Naive Bayes for improved accuracy."""

import json
import pickle
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, cast

import numpy as np
from sqlalchemy.orm import Session

from ..core.config import MLConfig
from ..core.database import CategoryORM, ModelMetadataORM, TransactionORM
from ..core.models import TransactionInput, TransactionPrediction
from .categorizer import TransactionCategorizer
from .cross_validation import StratifiedKFoldValidator
from .naive_bayes_classifier import NaiveBayesTextClassifier


class EnsembleCategorizer:
    """Ensemble categorizer combining LightGBM and Naive Bayes models."""

    def __init__(self, session: Session, config: MLConfig) -> None:
        self.session = session
        self.config = config

        # Component models
        self.lgbm_component = TransactionCategorizer(session, config)
        self.nb_component = NaiveBayesTextClassifier(
            alpha=getattr(config, "nb_alpha", 1.0),
            use_complement=getattr(config, "nb_use_complement", True),
            max_features=getattr(config, "nb_max_features", 2000),
        )

        # Cross-validation framework
        self.cv_validator = StratifiedKFoldValidator(n_splits=getattr(config, "ensemble_cv_folds", 5), random_state=42)

        # Ensemble parameters
        self.ensemble_weights = {"lgbm": 0.7, "nb": 0.3}  # Default weights
        self.is_trained = False
        self.cv_results: dict[str, Any] | None = None
        self.model_version = "1.0-ensemble"

    def prepare_training_data(self) -> tuple[list[TransactionInput], np.ndarray]:
        """Prepare training data from database transactions."""
        # Get transactions with confirmed categories (same as TransactionCategorizer)
        query = self.session.query(TransactionORM).filter(TransactionORM.category_id.isnot(None))
        transactions = query.all()

        if len(transactions) < self.config.min_training_samples:
            raise ValueError(
                f"Not enough training data. Need at least {self.config.min_training_samples} transactions."
            )

        # Filter out categories with too few samples for cross-validation
        min_samples_per_category = max(5, self.cv_validator.n_splits)  # Need at least 5 (or n_splits) for CV

        # Count transactions per category
        category_counts: dict[int, int] = {}
        for txn in transactions:
            cat_id = cast(int, txn.category_id)
            category_counts[cat_id] = category_counts.get(cat_id, 0) + 1

        # Filter categories with enough samples
        valid_categories = {cat_id for cat_id, count in category_counts.items() if count >= min_samples_per_category}

        if len(valid_categories) < 2:
            raise ValueError(f"Need at least 2 categories with {min_samples_per_category}+ samples each for training.")

        # Filter transactions to only include valid categories
        filtered_transactions = [txn for txn in transactions if txn.category_id in valid_categories]

        # Log filtering results
        excluded_categories = set(category_counts.keys()) - valid_categories
        if excluded_categories:
            excluded_names = []
            for cat_id in excluded_categories:
                category = self.session.query(CategoryORM).filter(CategoryORM.id == cat_id).first()
                if category:
                    excluded_names.append(f"{category.name} ({category_counts[cat_id]} samples)")
            print(f"⚠️  Excluding categories with <{min_samples_per_category} samples: {', '.join(excluded_names)}")

        print(
            f"📊 Training ensemble with {len(filtered_transactions)} transactions "
            f"across {len(valid_categories)} categories"
        )

        # Convert to TransactionInput format
        txn_inputs = []
        categories = []

        for txn in filtered_transactions:
            txn_input = TransactionInput(
                date=cast(date, txn.date),
                value_date=cast(date | None, txn.value_date),
                name=str(txn.name),
                purpose=str(txn.purpose or ""),
                amount=cast(float, txn.amount),
                currency=str(txn.currency),
            )
            txn_inputs.append(txn_input)
            categories.append(txn.category_id)

        return txn_inputs, np.array(categories)

    def train_with_validation_optimization(
        self, progress_callback: Callable[[str], None] | None = None
    ) -> dict[str, Any]:
        """Train ensemble with simple validation-based weight optimization.

        Args:
            progress_callback: Optional callback for progress updates. Called with phase name
                              (e.g., "training_nb", "optimizing_weights").
        """
        print("🔍 Preparing training data for ensemble...")
        transactions, labels = self.prepare_training_data()

        print(f"📝 Training ensemble on {len(transactions)} transactions...")

        # Split into train/validation for weight optimization
        from sklearn.model_selection import train_test_split

        train_transactions, val_transactions, train_labels, val_labels = train_test_split(
            transactions, labels, test_size=0.2, stratify=labels, random_state=42
        )

        print("🚀 Training individual models...")

        # Train LightGBM component
        print("  Training LightGBM...")
        lgbm_temp = TransactionCategorizer(self.session, self.config)
        lgbm_temp.fit(train_transactions, train_labels)

        # Train Naive Bayes component
        if progress_callback:
            progress_callback("training_nb")
        print("  Training Naive Bayes...")
        nb_temp = NaiveBayesTextClassifier(
            alpha=getattr(self.config, "nb_alpha", 1.0),
            use_complement=getattr(self.config, "nb_use_complement", True),
            max_features=getattr(self.config, "nb_max_features", 2000),
        )
        nb_temp.fit(train_transactions, train_labels)

        if progress_callback:
            progress_callback("optimizing_weights")
        print("🔄 Optimizing ensemble weights on validation set...")

        # Get probability vectors on validation set
        lgbm_val_probas_raw = lgbm_temp.predict_proba(val_transactions)
        nb_val_probas = nb_temp.predict_proba(val_transactions)

        # Align LightGBM probabilities to NB class order
        if nb_temp.classes_ is None:
            raise ValueError("Naive Bayes model must be fitted before converting predictions")
        lgbm_val_probas = self._align_probas(lgbm_val_probas_raw, lgbm_temp.classes_, nb_temp.classes_)

        # Test different weight combinations
        weight_candidates = [{"lgbm": w, "nb": 1 - w} for w in np.arange(0.3, 0.9, 0.1)]
        best_weights = {"lgbm": 0.7, "nb": 0.3}
        best_score = 0.0

        for weights in weight_candidates:
            # Combine predictions
            ensemble_probas = weights["lgbm"] * lgbm_val_probas + weights["nb"] * nb_val_probas
            ensemble_predictions = nb_temp.label_encoder.inverse_transform(np.argmax(ensemble_probas, axis=1))

            # Calculate accuracy
            from sklearn.metrics import accuracy_score

            score = accuracy_score(val_labels, ensemble_predictions)

            print(f"  Weights LightGBM={weights['lgbm']:.1f}, NB={weights['nb']:.1f}: {score:.4f}")

            if score > best_score:
                best_score = score
                best_weights = weights

        print(
            f"🎯 Best weights: LightGBM={best_weights['lgbm']:.1f}, "
            f"NB={best_weights['nb']:.1f} (accuracy: {best_score:.4f})"
        )

        # Set optimal weights
        self.ensemble_weights = best_weights

        # Train final models on full dataset
        print("🚀 Training final models on full dataset...")
        self.lgbm_component.fit(transactions, labels)
        self.nb_component.fit(transactions, labels)

        # Save results
        self.cv_results = {
            "best_weights": best_weights,
            "validation_accuracy": best_score,
            "weight_candidates": weight_candidates,
            "n_training_samples": len(transactions),
            "n_validation_samples": len(val_transactions),
        }

        # Update merchant mappings
        print("🏪 Updating merchant mappings...")
        self.lgbm_component.merchant_mapper.update_from_transactions()

        # Save model metadata
        self._save_ensemble_metadata()

        self.is_trained = True
        self.classes_ = self.nb_component.classes_
        print(f"✅ Ensemble training complete! Validation accuracy: {best_score:.3f}")

        return self.cv_results

    def _align_probas(
        self, probas: np.ndarray, source_classes: np.ndarray | None, target_classes: np.ndarray
    ) -> np.ndarray:
        """Align probability matrix columns from source class order to target class order.

        Args:
            probas: Probability matrix of shape (n_samples, n_source_classes).
            source_classes: Class labels corresponding to columns of probas.
            target_classes: Desired class label order for output columns.

        Returns:
            Aligned probability matrix of shape (n_samples, n_target_classes),
            renormalized so rows sum to 1.
        """
        if source_classes is None:
            return np.ones((probas.shape[0], len(target_classes))) / len(target_classes)

        n_samples = probas.shape[0]
        n_target = len(target_classes)
        aligned = np.zeros((n_samples, n_target))

        source_class_list = list(source_classes)
        for i, cls in enumerate(target_classes):
            if cls in source_class_list:
                src_idx = source_class_list.index(cls)
                aligned[:, i] = probas[:, src_idx]

        row_sums = aligned.sum(axis=1, keepdims=True)
        row_sums[row_sums == 0] = 1  # avoid division by zero
        aligned = aligned / row_sums
        return aligned

    def _align_single_proba(
        self, probas: np.ndarray, source_classes: np.ndarray | None, target_classes: np.ndarray | None
    ) -> np.ndarray:
        """Align a single probability vector from source class order to target class order.

        Args:
            probas: 1-D probability vector of shape (n_source_classes,).
            source_classes: Class labels corresponding to entries of probas.
            target_classes: Desired class label order for output.

        Returns:
            Aligned 1-D probability vector of shape (n_target_classes,),
            renormalized so entries sum to 1.
        """
        if source_classes is None or target_classes is None:
            return probas
        aligned_2d = self._align_probas(probas.reshape(1, -1), source_classes, target_classes)
        return aligned_2d[0]

    def predict_with_confidence(self, transactions: list[TransactionInput]) -> list[TransactionPrediction]:
        """Ensemble prediction combining LightGBM + Naive Bayes."""
        if not self.is_trained:
            raise ValueError("Ensemble must be trained before prediction")

        predictions = []

        for txn in transactions:
            # First try rule-based merchant mapping (high confidence)
            merchant_match = self.lgbm_component.merchant_mapper.get_category(txn.name)
            if merchant_match and merchant_match.confidence >= 0.95:
                predictions.append(
                    TransactionPrediction(
                        transaction_id=txn.generate_id(),
                        predicted_category_id=merchant_match.category_id,
                        confidence_score=merchant_match.confidence,
                        feature_contributions={"merchant_rule": 1.0},
                    )
                )
                continue

            # Get full probability vectors from both models
            lgbm_probas_raw = self.lgbm_component.predict_proba([txn])[0]
            nb_probas = self.nb_component.predict_proba([txn])[0]

            # Align LightGBM probabilities to NB class order
            lgbm_probas = self._align_single_proba(
                lgbm_probas_raw, self.lgbm_component.classes_, self.nb_component.classes_
            )

            # Combine predictions using learned weights
            combined_probas = self.ensemble_weights["lgbm"] * lgbm_probas + self.ensemble_weights["nb"] * nb_probas

            # Get final prediction
            pred_idx = np.argmax(combined_probas)
            confidence = float(combined_probas[pred_idx])

            # Map back to category ID
            if hasattr(self.nb_component, "classes_") and self.nb_component.classes_ is not None:
                predicted_category_id = int(self.nb_component.classes_[pred_idx])
            else:
                predicted_category_id = int(self.lgbm_component.classes_[np.argmax(lgbm_probas_raw)])

            # Combine feature contributions from global importances
            feature_contributions = self._combine_feature_contributions(lgbm_probas, nb_probas)

            ensemble_pred = TransactionPrediction(
                transaction_id=txn.generate_id(),
                predicted_category_id=predicted_category_id,
                confidence_score=confidence,
                feature_contributions=feature_contributions,
            )

            predictions.append(ensemble_pred)

        return predictions

    def _combine_feature_contributions(self, lgbm_probas: np.ndarray, nb_probas: np.ndarray) -> dict[str, float]:
        """Combine feature contributions from both models using global importances."""
        contributions: dict[str, float] = {}

        lgbm_weight = self.ensemble_weights["lgbm"]
        nb_weight = self.ensemble_weights["nb"]

        # Use LightGBM's global feature importance (top 5)
        if hasattr(self.lgbm_component.classifier, "feature_importances_"):
            importances = self.lgbm_component.classifier.feature_importances_
            top_indices = np.argsort(importances)[-5:]
            total_imp = float(importances[top_indices].sum()) or 1.0
            for idx in top_indices:
                if idx < len(self.lgbm_component.feature_names):
                    name = self.lgbm_component.feature_names[idx]
                    contributions[f"lgbm_{name}"] = float(importances[idx]) / total_imp * lgbm_weight

        # Add Naive Bayes contribution summary
        nb_confidence = float(np.max(nb_probas))
        contributions["nb_text_features"] = nb_confidence * nb_weight

        # Add ensemble metadata
        contributions["ensemble_lgbm_weight"] = lgbm_weight
        contributions["ensemble_nb_weight"] = nb_weight

        return contributions

    def _save_ensemble_metadata(self) -> None:
        """Save ensemble model metadata to database."""
        # Deactivate previous models
        self.session.query(ModelMetadataORM).update({"is_active": False})

        # Create ensemble metadata
        cv_results = self.cv_results or {}
        metadata = ModelMetadataORM(
            model_version=self.model_version,
            accuracy=cv_results.get("validation_accuracy", 0.0),
            feature_importance=json.dumps({"ensemble_weights": self.ensemble_weights, "cv_results": self.cv_results}),
            parameters=json.dumps(
                {
                    "lgbm_params": self.config.lgbm_params,
                    "nb_alpha": getattr(self.config, "nb_alpha", 1.0),
                    "nb_use_complement": getattr(self.config, "nb_use_complement", True),
                    "nb_max_features": getattr(self.config, "nb_max_features", 2000),
                    "cv_folds": getattr(self.config, "ensemble_cv_folds", 5),
                }
            ),
            is_active=True,
        )

        self.session.add(metadata)
        self.session.commit()

    def save_model(self, model_path: Path) -> None:
        """Save trained ensemble model to disk."""
        if not self.is_trained:
            raise ValueError("Ensemble must be trained before saving")

        model_path.parent.mkdir(parents=True, exist_ok=True)

        # Create a copy of lgbm_component without the session to avoid pickle issues
        lgbm_model_data = {
            "classifier": self.lgbm_component.classifier,
            "calibrated_classifier": self.lgbm_component.calibrated_classifier,
            "text_vectorizer": self.lgbm_component.text_vectorizer,
            "label_encoder": self.lgbm_component.label_encoder,
            "feature_names": self.lgbm_component.feature_names,
            "classes_": self.lgbm_component.classes_,
            "model_version": self.lgbm_component.model_version,
            "config": self.lgbm_component.config.model_dump(),
        }

        ensemble_data = {
            "lgbm_model_data": lgbm_model_data,
            "nb_component": self.nb_component,
            "ensemble_weights": self.ensemble_weights,
            "cv_results": self.cv_results,
            "model_version": self.model_version,
            "config": self.config.model_dump(),
        }

        with open(model_path, "wb") as f:
            pickle.dump(ensemble_data, f)

    def load_model(self, model_path: Path) -> None:
        """Load trained ensemble model from disk."""
        with open(model_path, "rb") as f:
            try:
                ensemble_data = pickle.load(f)
            except ModuleNotFoundError as e:
                # Handle legacy pickle files with different module paths
                if "fafycat" in str(e):
                    # Create a custom unpickler that can handle the old module path
                    import pickle as _pickle

                    # Temporarily add the module mapping for old pickle files
                    class LegacyUnpickler(_pickle.Unpickler):
                        def find_class(self, module, name) -> Any:
                            # Map old module paths to new ones
                            if module.startswith("fafycat."):
                                # Remove the old 'fafycat.' prefix and use the current structure
                                new_module = module.replace("fafycat.", "src.fafycat.")
                                return super().find_class(new_module, name)
                            if module == "fafycat":
                                # Handle direct fafycat imports
                                return super().find_class("src.fafycat", name)
                            return super().find_class(module, name)

                    f.seek(0)  # Reset file pointer
                    unpickler = LegacyUnpickler(f)
                    ensemble_data = unpickler.load()
                else:
                    raise

        # Recreate lgbm_component from saved data
        if "lgbm_model_data" in ensemble_data:
            # New format - reconstruct TransactionCategorizer
            lgbm_data = ensemble_data["lgbm_model_data"]
            self.lgbm_component = TransactionCategorizer(self.session, self.config)
            self.lgbm_component.classifier = lgbm_data["classifier"]
            self.lgbm_component.calibrated_classifier = lgbm_data["calibrated_classifier"]
            self.lgbm_component.text_vectorizer = lgbm_data["text_vectorizer"]
            self.lgbm_component.label_encoder = lgbm_data["label_encoder"]
            self.lgbm_component.feature_names = lgbm_data["feature_names"]
            self.lgbm_component.classes_ = lgbm_data["classes_"]
            self.lgbm_component.model_version = lgbm_data["model_version"]
            self.lgbm_component.is_trained = True
        else:
            # Old format - direct assignment (legacy support)
            self.lgbm_component = ensemble_data["lgbm_component"]

        self.nb_component = ensemble_data["nb_component"]
        self.ensemble_weights = ensemble_data["ensemble_weights"]
        self.cv_results = ensemble_data["cv_results"]
        self.model_version = ensemble_data["model_version"]

        self.is_trained = True
        self.classes_ = self.lgbm_component.classes_

    def get_ensemble_explanation(self, transaction: TransactionInput) -> dict[str, Any]:
        """Get detailed explanation for ensemble prediction."""
        if not self.is_trained:
            raise ValueError("Ensemble must be trained before explanation")

        # Get individual model explanations
        lgbm_explanation = self.lgbm_component.get_prediction_explanation(transaction)
        nb_explanation = self.nb_component.get_prediction_explanation(transaction)

        # Get ensemble prediction
        ensemble_pred = self.predict_with_confidence([transaction])[0]

        return {
            "ensemble_prediction": ensemble_pred,
            "ensemble_weights": self.ensemble_weights,
            "lgbm_explanation": lgbm_explanation,
            "nb_explanation": nb_explanation,
            "cv_performance": {
                "validation_accuracy": (self.cv_results or {}).get("validation_accuracy", 0.0),
                "ensemble_weights": self.ensemble_weights,
            },
        }
