"""Main ML categorizer using LightGBM."""

import json
import pickle
from datetime import date
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from scipy.sparse import hstack as sparse_hstack
from sklearn.calibration import CalibratedClassifierCV
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.frozen import FrozenEstimator
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

        # ML components — combined char + word TF-IDF with SVD
        self.char_vectorizer = TfidfVectorizer(**config.tfidf_char_params)
        self.word_vectorizer: TfidfVectorizer | None = TfidfVectorizer(**config.tfidf_word_params)
        self.svd: TruncatedSVD | None = TruncatedSVD(n_components=config.svd_n_components, random_state=42)
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

        # Filter out categories with too few samples for cross-validation.
        # Each class must survive both the outer train_test_split (test_size=0.2)
        # and the inner CalibratedClassifierCV(cv=5) on the train slice, so we
        # need ceil(5 / 0.8) = 7 samples per class.
        min_samples_per_category = 7

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
                date=cast(date, txn.date),
                value_date=cast(date | None, txn.value_date),
                name=str(txn.name),
                purpose=str(txn.purpose or ""),
                amount=cast(float, txn.amount),
                currency=str(txn.currency),
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

        # Calibrate probabilities using FrozenEstimator with internal CV
        # Uses sigmoid (Platt scaling) — stable with small samples unlike isotonic
        # Calibrates on train set with 5-fold CV for pseudo-out-of-sample predictions
        print("Calibrating probabilities...")
        frozen = FrozenEstimator(self.classifier)
        min_class_count = int(np.min(np.bincount(y_train)))
        cv_folds = max(2, min(5, min_class_count))
        self.calibrated_classifier = CalibratedClassifierCV(frozen, method="sigmoid", cv=cv_folds)
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

    def fit(self, transactions: list[TransactionInput], labels: np.ndarray) -> None:
        """Train the model on pre-split data without DB access."""
        features_list = self.feature_extractor.extract_batch_features(transactions)
        X_df = pd.DataFrame(features_list)

        y_encoded = self.label_encoder.fit_transform(labels)
        self.classes_ = self.label_encoder.classes_

        X_prepared = self._prepare_features(X_df, fit=True)
        self.classifier.fit(X_prepared, y_encoded)

        # Calibrate on training data with internal CV
        frozen = FrozenEstimator(self.classifier)
        min_class_count = int(np.min(np.bincount(y_encoded)))
        cv_folds = max(2, min(5, min_class_count))
        self.calibrated_classifier = CalibratedClassifierCV(frozen, method="sigmoid", cv=cv_folds)
        self.calibrated_classifier.fit(X_prepared, y_encoded)

        self.is_trained = True

    @property
    def _has_combined_vectorizer(self) -> bool:
        """Check if the model uses the combined char+word+SVD pipeline."""
        return self.word_vectorizer is not None and self.svd is not None

    def _prepare_features(self, X_df: pd.DataFrame, fit: bool = False) -> np.ndarray:
        """Prepare features for ML model."""
        # Get numerical features
        numerical_features = self.feature_extractor.get_numerical_feature_names()
        X_numerical = X_df[numerical_features].fillna(0).values

        # Get text features
        text_features = X_df["text_combined"].fillna("").values

        if self._has_combined_vectorizer:
            # Combined char + word TF-IDF → SVD (keeps sparse until SVD)
            if fit:
                X_char = self.char_vectorizer.fit_transform(text_features)
                X_word = self.word_vectorizer.fit_transform(text_features)  # type: ignore[union-attr]
                X_text_sparse = sparse_hstack([X_char, X_word])
                X_text = self.svd.fit_transform(X_text_sparse)  # type: ignore[union-attr]
                self.feature_names = numerical_features + [f"svd_{i}" for i in range(X_text.shape[1])]
            else:
                X_char = self.char_vectorizer.transform(text_features)
                X_word = self.word_vectorizer.transform(text_features)  # type: ignore[union-attr]
                X_text_sparse = sparse_hstack([X_char, X_word])
                X_text = self.svd.transform(X_text_sparse)  # type: ignore[union-attr]
        else:
            # Legacy single-vectorizer path (for old saved models)
            if fit:
                X_text = self.char_vectorizer.fit_transform(text_features).toarray()
                self.feature_names = numerical_features + [f"text_{i}" for i in range(X_text.shape[1])]
            else:
                X_text = self.char_vectorizer.transform(text_features).toarray()

        # X_text is dense (SVD output or .toarray()) — safe to hstack
        X_combined = np.hstack([X_numerical, X_text])

        return X_combined

    def predict_with_confidence(self, transactions: list[TransactionInput]) -> list[TransactionPrediction]:
        """Predict categories with confidence scores.

        Uses batch ML inference for all transactions not resolved by merchant
        mapping, avoiding per-transaction feature extraction and model calls.
        """
        if not self.is_trained:
            raise ValueError("Model must be trained before prediction")
        if self.classes_ is None:
            raise ValueError("Model has no classes_ — was it trained?")

        predictions: list[TransactionPrediction | None] = [None] * len(transactions)
        ml_indices: list[int] = []
        ml_transactions: list[TransactionInput] = []

        # Phase 1: Merchant mapper (fast, rule-based)
        for i, txn in enumerate(transactions):
            merchant_match = self.merchant_mapper.get_category(txn.name)
            if merchant_match and merchant_match.confidence >= 0.95:
                predictions[i] = TransactionPrediction(
                    transaction_id=txn.generate_id(),
                    predicted_category_id=merchant_match.category_id,
                    confidence_score=merchant_match.confidence,
                    feature_contributions={"merchant_rule": 1.0},
                )
            else:
                ml_indices.append(i)
                ml_transactions.append(txn)

        # Phase 2: Batch ML prediction for remaining
        if ml_transactions:
            features_list = self.feature_extractor.extract_batch_features(ml_transactions)
            X_df = pd.DataFrame(features_list)
            X_prepared = self._prepare_features(X_df, fit=False)

            try:
                if self.calibrated_classifier:
                    probas = self.calibrated_classifier.predict_proba(X_prepared)
                else:
                    probas = self.classifier.predict_proba(X_prepared)
            except ValueError:
                probas = self.classifier.predict_proba(X_prepared)

            for j, idx in enumerate(ml_indices):
                proba = probas[j]
                pred_idx = np.argmax(proba)
                confidence = float(proba[pred_idx])
                predicted_category_id = int(self.classes_[pred_idx])
                feature_contributions = self._get_feature_contributions(X_prepared[j], int(pred_idx))

                predictions[idx] = TransactionPrediction(
                    transaction_id=ml_transactions[j].generate_id(),
                    predicted_category_id=predicted_category_id,
                    confidence_score=confidence,
                    feature_contributions=feature_contributions,
                )

        return [p for p in predictions if p is not None]

    def predict_proba(self, transactions: list[TransactionInput]) -> np.ndarray:
        """Get full calibrated probability vectors, bypassing merchant mapper.

        Returns:
            Array of shape (n_transactions, n_classes) with calibrated probabilities.
        """
        if not self.is_trained:
            raise ValueError("Model must be trained before prediction")
        features_list = self.feature_extractor.extract_batch_features(transactions)
        X_df = pd.DataFrame(features_list)
        X_prepared = self._prepare_features(X_df, fit=False)
        if self.calibrated_classifier is not None:
            return self.calibrated_classifier.predict_proba(X_prepared)
        return self.classifier.predict_proba(X_prepared)

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
            "char_vectorizer": self.char_vectorizer,
            "word_vectorizer": self.word_vectorizer,
            "svd": self.svd,
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
        self.label_encoder = model_data["label_encoder"]
        self.feature_names = model_data["feature_names"]
        self.classes_ = model_data["classes_"]
        self.model_version = model_data["model_version"]

        # Load vectorizers with backward compat for old pickles
        self.char_vectorizer = model_data.get("char_vectorizer", model_data.get("text_vectorizer"))
        self.word_vectorizer = model_data.get("word_vectorizer", None)
        self.svd = model_data.get("svd", None)

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
