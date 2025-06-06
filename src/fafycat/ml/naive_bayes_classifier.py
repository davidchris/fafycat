"""Naive Bayes text classifier for transaction categorization."""

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import ComplementNB, MultinomialNB
from sklearn.preprocessing import LabelEncoder

from ..core.models import TransactionInput


class NaiveBayesTextClassifier:
    """Naive Bayes classifier focused on text features for transaction categorization."""

    def __init__(self, alpha: float = 1.0, use_complement: bool = True, max_features: int = 2000):
        """Initialize the Naive Bayes text classifier.

        Args:
            alpha: Smoothing parameter for Naive Bayes
            use_complement: Use ComplementNB (better for imbalanced data) vs MultinomialNB
            max_features: Maximum number of TF-IDF features
        """
        self.alpha = alpha
        self.use_complement = use_complement
        self.max_features = max_features

        # Text vectorizer optimized for transaction text
        self.vectorizer = TfidfVectorizer(
            ngram_range=(1, 3),  # Unigrams, bigrams, trigrams for better merchant patterns
            max_features=max_features,
            min_df=2,  # Must appear in at least 2 documents
            max_df=0.95,  # Ignore terms in >95% of documents
            lowercase=True,
            strip_accents="unicode",  # Handle German characters
            token_pattern=r"\b\w+\b",  # Word boundaries
        )

        # Choose Naive Bayes variant
        if use_complement:
            self.classifier = ComplementNB(alpha=alpha)
        else:
            self.classifier = MultinomialNB(alpha=alpha)

        self.label_encoder = LabelEncoder()
        self.classes_: np.ndarray | None = None
        self.is_fitted = False

    def _extract_text_features(self, transactions: list[TransactionInput]) -> list[str]:
        """Extract combined text features from transactions."""
        text_features = []

        for txn in transactions:
            # Combine merchant name and purpose with space separation
            combined_text = f"{txn.name} {txn.purpose or ''}"

            # Clean and normalize text
            combined_text = combined_text.strip().lower()

            text_features.append(combined_text)

        return text_features

    def fit(self, transactions: list[TransactionInput], labels: np.ndarray) -> None:
        """Train the Naive Bayes classifier on transaction text."""
        if len(transactions) != len(labels):
            raise ValueError("Number of transactions must match number of labels")

        # Extract text features
        text_features = self._extract_text_features(transactions)

        # Encode labels
        labels_encoded = self.label_encoder.fit_transform(labels)
        self.classes_ = self.label_encoder.classes_

        # Vectorize text
        X_text = self.vectorizer.fit_transform(text_features)

        # Train classifier
        self.classifier.fit(X_text, labels_encoded)

        self.is_fitted = True

    def predict_proba(self, transactions: list[TransactionInput]) -> np.ndarray:
        """Get prediction probabilities for transactions."""
        if not self.is_fitted:
            raise ValueError("Classifier must be fitted before prediction")

        # Extract text features
        text_features = self._extract_text_features(transactions)

        # Vectorize text
        X_text = self.vectorizer.transform(text_features)

        # Get probabilities
        probabilities = self.classifier.predict_proba(X_text)

        return probabilities

    def predict(self, transactions: list[TransactionInput]) -> np.ndarray:
        """Get class predictions for transactions."""
        probabilities = self.predict_proba(transactions)
        predictions = np.argmax(probabilities, axis=1)

        # Convert back to original label space
        return self.label_encoder.inverse_transform(predictions)

    def get_feature_importance(self, top_k: int = 20) -> dict[str, float]:
        """Get feature importance based on feature log probabilities."""
        if not self.is_fitted:
            raise ValueError("Classifier must be fitted before getting feature importance")

        # Get feature names
        feature_names = self.vectorizer.get_feature_names_out()

        if hasattr(self.classifier, "feature_log_prob_"):
            # For MultinomialNB and ComplementNB
            # Average log probabilities across classes
            avg_log_probs = np.mean(self.classifier.feature_log_prob_, axis=0)

            # Get top features
            top_indices = np.argsort(avg_log_probs)[-top_k:]

            importance_dict = {}
            for idx in top_indices:
                feature_name = feature_names[idx]
                importance = float(avg_log_probs[idx])
                importance_dict[feature_name] = importance

            return importance_dict
        # Fallback: use feature count importance
        return {}

    def get_prediction_explanation(self, transaction: TransactionInput) -> dict[str, any]:
        """Get explanation for a single prediction."""
        if not self.is_fitted:
            raise ValueError("Classifier must be fitted before explanation")

        # Get prediction and probabilities
        probabilities = self.predict_proba([transaction])[0]
        predicted_class_idx = np.argmax(probabilities)
        confidence = float(probabilities[predicted_class_idx])
        predicted_label = self.label_encoder.inverse_transform([predicted_class_idx])[0]

        # Get text features
        text_feature = self._extract_text_features([transaction])[0]

        # Get feature contributions (simplified version)
        feature_names = self.vectorizer.get_feature_names_out()
        X_text = self.vectorizer.transform([text_feature])

        # Get active features (non-zero TF-IDF values)
        active_features = {}
        for idx in X_text.nonzero()[1]:
            feature_name = feature_names[idx]
            tfidf_value = float(X_text[0, idx])
            active_features[feature_name] = tfidf_value

        # Sort by TF-IDF value and take top features
        top_features = dict(sorted(active_features.items(), key=lambda x: x[1], reverse=True)[:10])

        return {
            "predicted_label": predicted_label,
            "confidence": confidence,
            "text_input": text_feature,
            "top_text_features": top_features,
            "class_probabilities": {
                self.label_encoder.inverse_transform([i])[0]: float(prob) for i, prob in enumerate(probabilities)
            },
        }

    def get_model_info(self) -> dict[str, any]:
        """Get information about the trained model."""
        if not self.is_fitted:
            return {"status": "not_fitted"}

        return {
            "status": "fitted",
            "model_type": "ComplementNB" if self.use_complement else "MultinomialNB",
            "alpha": self.alpha,
            "n_features": len(self.vectorizer.get_feature_names_out())
            if hasattr(self.vectorizer, "get_feature_names_out")
            else 0,
            "n_classes": len(self.classes_) if self.classes_ is not None else 0,
            "classes": self.classes_.tolist() if self.classes_ is not None else [],
            "vectorizer_params": self.vectorizer.get_params(),
        }
