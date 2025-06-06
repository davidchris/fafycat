"""Ensemble categorizer combining LightGBM and Naive Bayes for improved accuracy."""

import json
import pickle
from pathlib import Path
from typing import Any

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

    def __init__(self, session: Session, config: MLConfig):
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
        self.cv_results = None
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
        min_samples_per_category = max(3, self.cv_validator.n_splits)  # Need at least n_splits samples for CV

        # Count transactions per category
        category_counts = {}
        for txn in transactions:
            category_counts[txn.category_id] = category_counts.get(txn.category_id, 0) + 1

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
                date=txn.date,
                value_date=txn.value_date,
                name=txn.name,
                purpose=txn.purpose or "",
                amount=txn.amount,
                currency=txn.currency,
            )
            txn_inputs.append(txn_input)
            categories.append(txn.category_id)

        return txn_inputs, np.array(categories)

    def train_with_validation_optimization(self) -> dict[str, Any]:
        """Train ensemble with simple validation-based weight optimization."""
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
        lgbm_temp.train(test_size=0.0)  # Use all available data in the current session

        # Train Naive Bayes component
        print("  Training Naive Bayes...")
        nb_temp = NaiveBayesTextClassifier(
            alpha=getattr(self.config, "nb_alpha", 1.0),
            use_complement=getattr(self.config, "nb_use_complement", True),
            max_features=getattr(self.config, "nb_max_features", 2000),
        )
        nb_temp.fit(train_transactions, train_labels)

        print("🔄 Optimizing ensemble weights on validation set...")

        # Get predictions on validation set
        lgbm_val_preds = lgbm_temp.predict_with_confidence(val_transactions)
        nb_val_probas = nb_temp.predict_proba(val_transactions)

        # Convert LightGBM predictions to probabilities
        lgbm_val_probas = self._convert_lgbm_predictions_to_probas(lgbm_val_preds, nb_temp.classes_)

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
        self.lgbm_component.train(test_size=0.0)
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
        print(f"✅ Ensemble training complete! Validation accuracy: {best_score:.3f}")

        return self.cv_results

    def _convert_lgbm_predictions_to_probas(self, lgbm_preds: list, nb_classes: np.ndarray) -> np.ndarray:
        """Convert LightGBM predictions to probability matrix matching NB classes."""
        n_samples = len(lgbm_preds)
        n_classes = len(nb_classes)
        probas = np.zeros((n_samples, n_classes))

        for i, pred in enumerate(lgbm_preds):
            # Find class index in NB classes
            class_idx = np.where(nb_classes == pred.predicted_category_id)[0]
            if len(class_idx) > 0:
                probas[i, class_idx[0]] = pred.confidence_score
                # Distribute remaining probability
                remaining = 1.0 - pred.confidence_score
                other_prob = remaining / (n_classes - 1)
                for j in range(n_classes):
                    if j != class_idx[0]:
                        probas[i, j] = other_prob
            else:
                # Uniform distribution if class not found
                probas[i, :] = 1.0 / n_classes

        return probas

    def _create_lgbm_wrapper_class(self):
        """Create a wrapper class for LightGBM that matches the interface expected by CV."""

        class LightGBMWrapper:
            def __init__(self, session: Session, config: MLConfig):
                self.categorizer = TransactionCategorizer(session, config)
                self.label_encoder = None

            def fit(self, transactions: list[TransactionInput], labels: np.ndarray):
                # Convert labels to appropriate format and store the encoder
                from sklearn.preprocessing import LabelEncoder

                self.label_encoder = LabelEncoder()
                self.label_encoder.fit_transform(labels)

                # We need to temporarily store the transactions with labels in the database
                # This is a simplified approach - in practice you might want a more sophisticated method
                # For now, we'll just use the existing train method
                self.categorizer.train(test_size=0.0)

            def predict_proba(self, transactions: list[TransactionInput]) -> np.ndarray:
                predictions = self.categorizer.predict_with_confidence(transactions)

                # Convert to probability matrix
                n_classes = len(self.label_encoder.classes_)
                probas = np.zeros((len(transactions), n_classes))

                for i, pred in enumerate(predictions):
                    # Find the class index
                    if pred.predicted_category_id in self.label_encoder.classes_:
                        class_idx = np.where(self.label_encoder.classes_ == pred.predicted_category_id)[0][0]
                        # Set high probability for predicted class, low for others
                        probas[i, class_idx] = pred.confidence_score
                        # Distribute remaining probability equally among other classes
                        remaining_prob = 1.0 - pred.confidence_score
                        other_prob = remaining_prob / (n_classes - 1)
                        for j in range(n_classes):
                            if j != class_idx:
                                probas[i, j] = other_prob
                    else:
                        # Uniform distribution if category not in training set
                        probas[i, :] = 1.0 / n_classes

                return probas

            def predict(self, transactions: list[TransactionInput]) -> np.ndarray:
                probas = self.predict_proba(transactions)
                predictions = np.argmax(probas, axis=1)
                return self.label_encoder.inverse_transform(predictions)

        return LightGBMWrapper

    def predict_with_confidence(self, transactions: list[TransactionInput]) -> list[TransactionPrediction]:
        """Ensemble prediction combining LightGBM + Naive Bayes."""
        if not self.is_trained:
            raise ValueError("Ensemble must be trained before prediction")

        predictions = []

        for txn in transactions:
            # First try rule-based merchant mapping (high confidence)
            merchant_match = self.lgbm_component.merchant_mapper.get_category(txn.name)
            if merchant_match and merchant_match.confidence > 0.95:
                predictions.append(
                    TransactionPrediction(
                        transaction_id=txn.generate_id(),
                        predicted_category_id=merchant_match.category_id,
                        confidence_score=merchant_match.confidence,
                        feature_contributions={"merchant_rule": 1.0},
                    )
                )
                continue

            # Get LightGBM prediction
            lgbm_pred = self.lgbm_component.predict_with_confidence([txn])[0]

            # Get Naive Bayes prediction
            nb_probas = self.nb_component.predict_proba([txn])[0]

            # Convert LightGBM prediction to probability distribution
            lgbm_probas = self._convert_lgbm_to_probas(lgbm_pred)

            # Combine predictions using learned weights
            combined_probas = self.ensemble_weights["lgbm"] * lgbm_probas + self.ensemble_weights["nb"] * nb_probas

            # Get final prediction
            pred_idx = np.argmax(combined_probas)
            confidence = float(combined_probas[pred_idx])

            # Map back to category ID
            if hasattr(self.nb_component, "classes_") and self.nb_component.classes_ is not None:
                predicted_category_id = int(self.nb_component.classes_[pred_idx])
            else:
                predicted_category_id = lgbm_pred.predicted_category_id

            # Combine feature contributions
            feature_contributions = self._combine_feature_contributions(lgbm_pred, nb_probas)

            ensemble_pred = TransactionPrediction(
                transaction_id=txn.generate_id(),
                predicted_category_id=predicted_category_id,
                confidence_score=confidence,
                feature_contributions=feature_contributions,
            )

            predictions.append(ensemble_pred)

        return predictions

    def _convert_lgbm_to_probas(self, lgbm_pred: TransactionPrediction) -> np.ndarray:
        """Convert LightGBM prediction to probability distribution."""
        if not hasattr(self.lgbm_component, "classes_") or self.lgbm_component.classes_ is None:
            # Fallback: create uniform distribution
            n_classes = len(self.nb_component.classes_) if hasattr(self.nb_component, "classes_") else 5
            probas = np.ones(n_classes) / n_classes
            return probas

        n_classes = len(self.lgbm_component.classes_)
        probas = np.zeros(n_classes)

        # Find the predicted class index
        pred_class_idx = np.where(self.lgbm_component.classes_ == lgbm_pred.predicted_category_id)[0]

        if len(pred_class_idx) > 0:
            probas[pred_class_idx[0]] = lgbm_pred.confidence_score
            # Distribute remaining probability among other classes
            remaining_prob = 1.0 - lgbm_pred.confidence_score
            other_prob = remaining_prob / (n_classes - 1)
            for i in range(n_classes):
                if i != pred_class_idx[0]:
                    probas[i] = other_prob
        else:
            # Uniform distribution if class not found
            probas[:] = 1.0 / n_classes

        return probas

    def _combine_feature_contributions(
        self, lgbm_pred: TransactionPrediction, nb_probas: np.ndarray
    ) -> dict[str, float]:
        """Combine feature contributions from both models."""
        contributions = {}

        # Add LightGBM contributions with weight
        lgbm_weight = self.ensemble_weights["lgbm"]
        for feature, contrib in lgbm_pred.feature_contributions.items():
            contributions[f"lgbm_{feature}"] = contrib * lgbm_weight

        # Add Naive Bayes contribution
        nb_weight = self.ensemble_weights["nb"]
        nb_confidence = float(np.max(nb_probas))
        contributions["nb_text_features"] = nb_confidence * nb_weight

        # Add ensemble metadata
        contributions["ensemble_lgbm_weight"] = lgbm_weight
        contributions["ensemble_nb_weight"] = nb_weight

        return contributions

    def _calculate_cv_metrics(self, transactions: list[TransactionInput], labels: np.ndarray) -> dict[str, Any]:
        """Calculate comprehensive cross-validation metrics."""
        # Compare individual models vs ensemble
        models_config = {
            "lightgbm": {
                "class": self._create_lgbm_wrapper_class(),
                "params": {"session": self.session, "config": self.config},
            },
            "naive_bayes": {
                "class": NaiveBayesTextClassifier,
                "params": {
                    "alpha": getattr(self.config, "nb_alpha", 1.0),
                    "use_complement": getattr(self.config, "nb_use_complement", True),
                    "max_features": getattr(self.config, "nb_max_features", 2000),
                },
            },
        }

        print("📈 Comparing individual model performance...")
        individual_results = self.cv_validator.compare_models(transactions, labels, models_config)

        # Get fold split information
        split_info = self.cv_validator.get_fold_splits_info(labels)

        return {
            "individual_models": individual_results,
            "fold_split_info": split_info,
            "ensemble_improvement": {
                "vs_lgbm": self.cv_results["best_cv_score"] - individual_results["lightgbm"]["cv_accuracy_mean"]
                if individual_results
                else 0,
                "vs_nb": self.cv_results["best_cv_score"] - individual_results["naive_bayes"]["cv_accuracy_mean"]
                if individual_results
                else 0,
            },
        }

    def _save_ensemble_metadata(self) -> None:
        """Save ensemble model metadata to database."""
        # Deactivate previous models
        self.session.query(ModelMetadataORM).update({"is_active": False})

        # Create ensemble metadata
        metadata = ModelMetadataORM(
            model_version=self.model_version,
            accuracy=self.cv_results["validation_accuracy"],
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
            ensemble_data = pickle.load(f)

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
                "validation_accuracy": self.cv_results["validation_accuracy"],
                "ensemble_weights": self.ensemble_weights,
            },
        }
