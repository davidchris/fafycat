"""Cross-validation framework for ensemble model evaluation and optimization."""

from typing import Any

import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import StratifiedKFold

from ..core.models import TransactionInput


class StratifiedKFoldValidator:
    """K-fold cross-validation for transaction categorization models."""

    def __init__(self, n_splits: int = 5, shuffle: bool = True, random_state: int = 42):
        """Initialize the k-fold validator.

        Args:
            n_splits: Number of folds for cross-validation
            shuffle: Whether to shuffle data before splitting
            random_state: Random seed for reproducibility
        """
        self.n_splits = n_splits
        self.shuffle = shuffle
        self.random_state = random_state
        self.skf = StratifiedKFold(n_splits=n_splits, shuffle=shuffle, random_state=random_state)

    def validate_single_model(
        self, transactions: list[TransactionInput], labels: np.ndarray, model_class: type, model_params: dict = None
    ) -> dict[str, Any]:
        """Perform k-fold cross-validation on a single model.

        Args:
            transactions: List of transaction inputs
            labels: True category labels
            model_class: Class of the model to validate
            model_params: Parameters to pass to model constructor

        Returns:
            Dictionary with CV results
        """
        if model_params is None:
            model_params = {}

        fold_scores = []
        fold_predictions = []
        fold_true_labels = []
        all_feature_importance = []

        # Convert to arrays for indexing
        transactions_array = np.array(transactions)

        for fold_idx, (train_idx, val_idx) in enumerate(self.skf.split(transactions, labels)):
            print(f"  Fold {fold_idx + 1}/{self.n_splits}")

            # Split data
            train_transactions = transactions_array[train_idx].tolist()
            val_transactions = transactions_array[val_idx].tolist()
            train_labels = labels[train_idx]
            val_labels = labels[val_idx]

            # Train model
            model = model_class(**model_params)
            model.fit(train_transactions, train_labels)

            # Predict on validation set
            val_predictions = model.predict(val_transactions)

            # Calculate fold accuracy
            fold_accuracy = accuracy_score(val_labels, val_predictions)
            fold_scores.append(fold_accuracy)

            # Store predictions for overall metrics
            fold_predictions.extend(val_predictions)
            fold_true_labels.extend(val_labels)

            # Get feature importance if available
            if hasattr(model, "get_feature_importance"):
                importance = model.get_feature_importance()
                all_feature_importance.append(importance)

        # Calculate overall metrics
        overall_accuracy = accuracy_score(fold_true_labels, fold_predictions)
        precision, recall, _, support = precision_recall_fscore_support(
            fold_true_labels, fold_predictions, average=None, zero_division=0
        )

        # Get unique labels for per-class metrics
        unique_labels = np.unique(labels)
        precision_per_class = {str(label): float(prec) for label, prec in zip(unique_labels, precision, strict=False)}
        recall_per_class = {str(label): float(rec) for label, rec in zip(unique_labels, recall, strict=False)}

        return {
            "cv_accuracy_mean": float(np.mean(fold_scores)),
            "cv_accuracy_std": float(np.std(fold_scores)),
            "cv_accuracy_scores": [float(score) for score in fold_scores],
            "overall_accuracy": float(overall_accuracy),
            "precision_per_class": precision_per_class,
            "recall_per_class": recall_per_class,
            "confusion_matrix": confusion_matrix(fold_true_labels, fold_predictions).tolist(),
            "feature_importance": all_feature_importance[0] if all_feature_importance else {},
        }

    def validate_ensemble_weights(
        self,
        transactions: list[TransactionInput],
        labels: np.ndarray,
        lgbm_model_class: type,
        nb_model_class: type,
        weight_candidates: list[dict[str, float]],
        lgbm_params: dict = None,
        nb_params: dict = None,
    ) -> tuple[dict[str, float], float, list[float]]:
        """Find optimal ensemble weights using k-fold cross-validation.

        Args:
            transactions: List of transaction inputs
            labels: True category labels
            lgbm_model_class: LightGBM model class
            nb_model_class: Naive Bayes model class
            weight_candidates: List of weight combinations to try
            lgbm_params: Parameters for LightGBM model
            nb_params: Parameters for Naive Bayes model

        Returns:
            Tuple of (best_weights, best_score, all_scores)
        """
        if lgbm_params is None:
            lgbm_params = {}
        if nb_params is None:
            nb_params = {}

        best_weights = None
        best_score = 0
        all_weight_scores = []

        print(f"Testing {len(weight_candidates)} weight combinations...")

        for weight_idx, weights in enumerate(weight_candidates):
            print(f"  Testing weights: LightGBM={weights['lgbm']:.1f}, NB={weights['nb']:.1f}")

            fold_scores = []
            transactions_array = np.array(transactions)

            for fold_idx, (train_idx, val_idx) in enumerate(self.skf.split(transactions, labels)):
                # Split data
                train_transactions = transactions_array[train_idx].tolist()
                val_transactions = transactions_array[val_idx].tolist()
                train_labels = labels[train_idx]
                val_labels = labels[val_idx]

                # Train both models
                lgbm_model = lgbm_model_class(**lgbm_params)
                nb_model = nb_model_class(**nb_params)

                lgbm_model.fit(train_transactions, train_labels)
                nb_model.fit(train_transactions, train_labels)

                # Get predictions from both models
                lgbm_probas = lgbm_model.predict_proba(val_transactions)
                nb_probas = nb_model.predict_proba(val_transactions)

                # Combine predictions with current weights
                ensemble_probas = weights["lgbm"] * lgbm_probas + weights["nb"] * nb_probas

                # Get ensemble predictions
                ensemble_predictions = np.argmax(ensemble_probas, axis=1)

                # Convert back to original label space
                if hasattr(lgbm_model, "label_encoder"):
                    ensemble_predictions = lgbm_model.label_encoder.inverse_transform(ensemble_predictions)

                # Calculate accuracy
                fold_accuracy = accuracy_score(val_labels, ensemble_predictions)
                fold_scores.append(fold_accuracy)

            # Calculate mean score for this weight combination
            mean_score = np.mean(fold_scores)
            all_weight_scores.append(mean_score)

            print(f"    Mean CV accuracy: {mean_score:.4f} ± {np.std(fold_scores):.4f}")

            # Update best weights if this is better
            if mean_score > best_score:
                best_score = mean_score
                best_weights = weights

        print(f"Best weights: LightGBM={best_weights['lgbm']:.1f}, NB={best_weights['nb']:.1f}")
        print(f"Best CV accuracy: {best_score:.4f}")

        return best_weights, best_score, all_weight_scores

    def compare_models(
        self, transactions: list[TransactionInput], labels: np.ndarray, models_config: dict[str, dict]
    ) -> dict[str, dict[str, Any]]:
        """Compare multiple models using k-fold cross-validation.

        Args:
            transactions: List of transaction inputs
            labels: True category labels
            models_config: Dictionary mapping model names to config dicts
                          Each config should have 'class' and optionally 'params'

        Returns:
            Dictionary mapping model names to their CV results
        """
        results = {}

        for model_name, config in models_config.items():
            print(f"Evaluating {model_name}...")

            model_class = config["class"]
            model_params = config.get("params", {})

            cv_results = self.validate_single_model(transactions, labels, model_class, model_params)

            results[model_name] = cv_results

            print(
                f"  {model_name} CV accuracy: {cv_results['cv_accuracy_mean']:.4f} ± {cv_results['cv_accuracy_std']:.4f}"
            )

        return results

    def get_fold_splits_info(self, labels: np.ndarray) -> dict[str, Any]:
        """Get information about how data is split across folds.

        Args:
            labels: True category labels

        Returns:
            Dictionary with split information
        """
        fold_info = {"n_splits": self.n_splits, "total_samples": len(labels), "splits": []}

        for fold_idx, (train_idx, val_idx) in enumerate(self.skf.split(range(len(labels)), labels)):
            # Count labels in train and validation sets
            train_labels = labels[train_idx]
            val_labels = labels[val_idx]

            unique_labels, train_counts = np.unique(train_labels, return_counts=True)
            unique_labels, val_counts = np.unique(val_labels, return_counts=True)

            split_info = {
                "fold": fold_idx + 1,
                "train_size": len(train_idx),
                "val_size": len(val_idx),
                "train_label_counts": dict(zip(unique_labels.astype(str), train_counts.tolist(), strict=False)),
                "val_label_counts": dict(zip(unique_labels.astype(str), val_counts.tolist(), strict=False)),
            }

            fold_info["splits"].append(split_info)

        return fold_info
