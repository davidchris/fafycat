"""Main ML categorizer using LightGBM."""

import json
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sqlalchemy.orm import Session

from ..core.config import MLConfig
from ..core.database import CategoryORM, ModelMetadataORM, TransactionORM
from ..core.models import ModelMetrics, TransactionInput, TransactionPrediction
from .feature_extractor import FeatureExtractor
from .merchant_mapper import MerchantMapper


class TransactionCategorizer:
    """Main ML model for transaction categorization."""

    def __init__(self, session: Session, config: MLConfig):
        self.session = session
        self.config = config
        self.feature_extractor = FeatureExtractor()
        self.merchant_mapper = MerchantMapper(session)

        # ML components
        self.text_vectorizer = TfidfVectorizer(**config.tfidf_params)
        self.label_encoder = LabelEncoder()
        self.classifier = LGBMClassifier(**config.lgbm_params)
        self.calibrated_classifier: CalibratedClassifierCV | None = None

        # Model metadata
        self.feature_names: list[str] = []
        self.classes_: np.ndarray | None = None
        self.is_trained = False
        self.model_version = "1.0"

    def prepare_training_data(self) -> tuple[pd.DataFrame, np.ndarray]:
        """Prepare training data from database transactions."""
        # Get transactions with confirmed categories
        query = self.session.query(TransactionORM).filter(TransactionORM.category_id.isnot(None))

        transactions = query.all()

        if len(transactions) < self.config.min_training_samples:
            raise ValueError(
                f"Not enough training data. Need at least {self.config.min_training_samples} transactions."
            )

        # Filter out categories with too few samples for cross-validation
        min_samples_per_category = 3  # Need at least 3 for CV

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

        print(f"📊 Training with {len(filtered_transactions)} transactions across {len(valid_categories)} categories")

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

        # Extract features
        features_list = self.feature_extractor.extract_batch_features(txn_inputs)

        # Convert to DataFrame
        df = pd.DataFrame(features_list)
        y = np.array(categories)

        return df, y

    def train(self, test_size: float = 0.2) -> ModelMetrics:
        """Train the categorization model."""
        print("Preparing training data...")
        X_df, y = self.prepare_training_data()

        print(f"Training on {len(X_df)} transactions...")

        # Encode labels
        y_encoded = self.label_encoder.fit_transform(y)
        self.classes_ = self.label_encoder.classes_

        # Split data or use all data if test_size is 0
        if test_size == 0.0:
            # Use all data for training (no test split)
            X_train, X_test = X_df, X_df
            y_train, y_test = y_encoded, y_encoded
        else:
            X_train, X_test, y_train, y_test = train_test_split(
                X_df, y_encoded, test_size=test_size, stratify=y_encoded, random_state=42
            )

        # Prepare features
        X_train_prepared = self._prepare_features(X_train, fit=True)
        X_test_prepared = self._prepare_features(X_test, fit=False)

        # Train classifier
        print("Training LightGBM classifier...")
        self.classifier.fit(X_train_prepared, y_train)

        # Calibrate probabilities
        print("Calibrating probabilities...")
        # Use cv=2 to handle small classes (need at least 2 samples per fold)
        # and fallback to sigmoid method if isotonic fails
        try:
            self.calibrated_classifier = CalibratedClassifierCV(self.classifier, cv=2, method="isotonic")
            self.calibrated_classifier.fit(X_train_prepared, y_train)
        except ValueError as e:
            print(f"Isotonic calibration failed ({e}), using sigmoid method...")
            self.calibrated_classifier = CalibratedClassifierCV(self.classifier, cv=2, method="sigmoid")
            self.calibrated_classifier.fit(X_train_prepared, y_train)

        # Calculate metrics
        print("Calculating metrics...")
        metrics = self._calculate_metrics(X_test_prepared, y_test)

        # Update merchant mappings
        print("Updating merchant mappings...")
        self.merchant_mapper.update_from_transactions()

        # Save model metadata
        self._save_model_metadata(metrics)

        self.is_trained = True
        print(f"Training complete! Accuracy: {metrics.accuracy:.3f}")

        return metrics

    def _prepare_features(self, X_df: pd.DataFrame, fit: bool = False) -> np.ndarray:
        """Prepare features for ML model."""
        # Get numerical features
        numerical_features = self.feature_extractor.get_numerical_feature_names()
        X_numerical = X_df[numerical_features].fillna(0).values

        # Get text features
        text_features = X_df["text_combined"].fillna("").values

        if fit:
            X_text = self.text_vectorizer.fit_transform(text_features)
            # Store feature names
            self.feature_names = numerical_features + [f"text_{i}" for i in range(X_text.shape[1])]
        else:
            X_text = self.text_vectorizer.transform(text_features)

        # Combine features
        X_combined = np.hstack([X_numerical, X_text.toarray()])

        return X_combined

    def predict_with_confidence(self, transactions: list[TransactionInput]) -> list[TransactionPrediction]:
        """Predict categories with confidence scores."""
        if not self.is_trained:
            raise ValueError("Model must be trained before prediction")

        predictions = []

        for txn in transactions:
            # First try rule-based merchant mapping
            merchant_match = self.merchant_mapper.get_category(txn.name)
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

            # Otherwise use ML model
            features = self.feature_extractor.extract_features(txn)
            features_df = pd.DataFrame([features])
            X_prepared = self._prepare_features(features_df, fit=False)

            # Get prediction and probability
            if self.calibrated_classifier:
                proba = self.calibrated_classifier.predict_proba(X_prepared)[0]
            else:
                proba = self.classifier.predict_proba(X_prepared)[0]

            pred_idx = np.argmax(proba)
            confidence = float(proba[pred_idx])
            predicted_category_id = int(self.classes_[pred_idx])

            # Get feature importance for this prediction
            feature_contributions = self._get_feature_contributions(X_prepared[0], pred_idx)

            predictions.append(
                TransactionPrediction(
                    transaction_id=txn.generate_id(),
                    predicted_category_id=predicted_category_id,
                    confidence_score=confidence,
                    feature_contributions=feature_contributions,
                )
            )

        return predictions

    def _get_feature_contributions(self, X_instance: np.ndarray, predicted_class: int) -> dict[str, float]:
        """Get feature contributions for explainability."""
        # Get feature importance from the model
        feature_importance = self.classifier.feature_importances_

        # Get top contributing features
        top_indices = np.argsort(feature_importance)[-10:]  # Top 10 features

        contributions = {}
        for idx in top_indices:
            if idx < len(self.feature_names):
                feature_name = self.feature_names[idx]
                # Combine importance with feature value
                contribution = float(feature_importance[idx] * abs(X_instance[idx]))
                contributions[feature_name] = contribution

        # Normalize contributions
        total = sum(contributions.values())
        if total > 0:
            contributions = {k: v / total for k, v in contributions.items()}

        return contributions

    def _calculate_metrics(self, X_test: np.ndarray, y_test: np.ndarray) -> ModelMetrics:
        """Calculate model performance metrics."""
        from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support

        # Predictions
        if self.calibrated_classifier:
            y_pred = self.calibrated_classifier.predict(X_test)
        else:
            y_pred = self.classifier.predict(X_test)

        # Overall accuracy
        accuracy = accuracy_score(y_test, y_pred)

        # Per-category metrics
        precision, recall, _, support = precision_recall_fscore_support(y_test, y_pred, average=None, zero_division=0)

        # Get category names
        category_names = {}
        if self.classes_ is None:
            return ModelMetrics(
                accuracy=accuracy,
                precision_per_category={},
                recall_per_category={},
                confusion_matrix=[],
                feature_importance={},
            )
        for category_id in self.classes_:
            category = self.session.query(CategoryORM).filter(CategoryORM.id == category_id).first()
            if category:
                category_names[str(category_id)] = category.name

        precision_per_category = {
            category_names.get(str(self.classes_[i]), f"category_{self.classes_[i]}"): float(precision[i])
            for i in range(len(precision))
        }

        recall_per_category = {
            category_names.get(str(self.classes_[i]), f"category_{self.classes_[i]}"): float(recall[i])
            for i in range(len(recall))
        }

        # Confusion matrix
        cm = confusion_matrix(y_test, y_pred)

        # Feature importance
        feature_importance = dict(
            zip(self.feature_names, [float(x) for x in self.classifier.feature_importances_], strict=False)
        )

        return ModelMetrics(
            accuracy=accuracy,
            precision_per_category=precision_per_category,
            recall_per_category=recall_per_category,
            confusion_matrix=cm.tolist(),
            feature_importance=feature_importance,
        )

    def _save_model_metadata(self, metrics: ModelMetrics) -> None:
        """Save model metadata to database."""
        # Deactivate previous models
        self.session.query(ModelMetadataORM).update({"is_active": False})

        # Create new model metadata
        metadata = ModelMetadataORM(
            model_version=self.model_version,
            accuracy=metrics.accuracy,
            feature_importance=json.dumps(metrics.feature_importance),
            parameters=json.dumps(self.config.lgbm_params),
            is_active=True,
        )

        self.session.add(metadata)
        self.session.commit()

    def save_model(self, model_path: Path) -> None:
        """Save trained model to disk."""
        if not self.is_trained:
            raise ValueError("Model must be trained before saving")

        model_path.parent.mkdir(parents=True, exist_ok=True)

        model_data = {
            "classifier": self.classifier,
            "calibrated_classifier": self.calibrated_classifier,
            "text_vectorizer": self.text_vectorizer,
            "label_encoder": self.label_encoder,
            "feature_names": self.feature_names,
            "classes_": self.classes_,
            "model_version": self.model_version,
            "config": self.config.model_dump(),
        }

        with open(model_path, "wb") as f:
            pickle.dump(model_data, f)

    def load_model(self, model_path: Path) -> None:
        """Load trained model from disk."""
        with open(model_path, "rb") as f:
            try:
                model_data = pickle.load(f)
            except ModuleNotFoundError as e:
                # Handle legacy pickle files with different module paths
                if "fafycat" in str(e):
                    # Create a custom unpickler that can handle the old module path
                    import pickle as _pickle

                    # Temporarily add the module mapping for old pickle files
                    class LegacyUnpickler(_pickle.Unpickler):
                        def find_class(self, module, name):
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
                    model_data = unpickler.load()
                else:
                    raise

        self.classifier = model_data["classifier"]
        self.calibrated_classifier = model_data["calibrated_classifier"]
        self.text_vectorizer = model_data["text_vectorizer"]
        self.label_encoder = model_data["label_encoder"]
        self.feature_names = model_data["feature_names"]
        self.classes_ = model_data["classes_"]
        self.model_version = model_data["model_version"]

        self.is_trained = True

    def get_prediction_explanation(self, transaction: TransactionInput) -> dict[str, Any]:
        """Get detailed explanation for a prediction."""
        if not self.is_trained:
            raise ValueError("Model must be trained before prediction")

        # Get prediction
        predictions = self.predict_with_confidence([transaction])
        prediction = predictions[0]

        # Get category name
        category = self.session.query(CategoryORM).filter(CategoryORM.id == prediction.predicted_category_id).first()

        # Get merchant suggestions
        merchant_suggestions = self.merchant_mapper.get_mapping_suggestions(transaction.name)

        return {
            "prediction": prediction,
            "category_name": category.name if category else "Unknown",
            "feature_contributions": prediction.feature_contributions,
            "merchant_suggestions": merchant_suggestions,
            "confidence_level": self._get_confidence_level(prediction.confidence_score),
        }

    def _get_confidence_level(self, confidence: float) -> str:
        """Convert confidence score to human-readable level."""
        if confidence >= self.config.confidence_thresholds["high"]:
            return "High"
        if confidence >= self.config.confidence_thresholds["medium"]:
            return "Medium"
        return "Low"
