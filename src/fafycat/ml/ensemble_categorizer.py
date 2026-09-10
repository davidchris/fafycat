"""Ensemble categorizer blending LightGBM, Naive Bayes, and the Merchant Rules.

All three are voters: each one turns a transaction into a probability vector
over the categories, and the ensemble adds them up with weights learned on a
validation split.
"""

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
from ..core.models import MerchantMapping, PredictionDetail, TransactionInput, TransactionPrediction
from .categorizer import TransactionCategorizer
from .cross_validation import StratifiedKFoldValidator
from .merchant_mapper import MerchantRuleSet, derive_rules
from .model_identity import model_fingerprint, probs_by_category
from .naive_bayes_classifier import NaiveBayesTextClassifier

DEFAULT_WEIGHTS = {"lgbm": 0.7, "nb": 0.3, "rule": 0.0}
"""Weights used until a training run learns better ones."""

MIN_MODEL_WEIGHT = 0.1
"""Neither model may be switched off: the grid keeps both at or above this."""


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    """Read voter weights that may predate the Merchant Rule voter.

    Args:
        weights: Weights loaded from a pickle or from model metadata.

    Returns:
        The same weights with a ``rule`` entry, 0.0 when the model was trained
        before rules became a voter.
    """
    return {"lgbm": weights["lgbm"], "nb": weights["nb"], "rule": weights.get("rule", 0.0)}


def active_ensemble_weights(session: Session) -> dict[str, float] | None:
    """Read the voter weights of the model currently in use.

    Args:
        session: Database session.

    Returns:
        The weights recorded by the last training run, or None when no ensemble
        has been trained.
    """
    row = (
        session.query(ModelMetadataORM)
        .filter(ModelMetadataORM.is_active.is_(True))
        .order_by(ModelMetadataORM.training_date.desc())
        .first()
    )
    if row is None or not row.feature_importance:
        return None
    weights = json.loads(str(row.feature_importance)).get("ensemble_weights")
    return normalize_weights(weights) if weights else None


def weight_grid(step: float = 0.1) -> list[dict[str, float]]:
    """Enumerate the voter weights to try, a simplex grid that sums to 1.

    Args:
        step: Grid resolution. Weights are multiples of this.

    Returns:
        Every ``{"lgbm", "nb", "rule"}`` combination summing to 1 with both
        models at or above ``MIN_MODEL_WEIGHT``. The rule may reach 0, which
        reproduces today's two-voter ensemble.
    """
    steps = round(1 / step)
    min_model_steps = round(MIN_MODEL_WEIGHT / step)
    grid: list[dict[str, float]] = []
    for lgbm in range(min_model_steps, steps + 1):
        for nb in range(min_model_steps, steps - lgbm + 1):
            grid.append(
                {
                    "lgbm": round(lgbm * step, 10),
                    "nb": round(nb * step, 10),
                    "rule": round((steps - lgbm - nb) * step, 10),
                }
            )
    return grid


def rule_probability_vector(rule: MerchantMapping | None, class_ids: list[int]) -> np.ndarray | None:
    """Turn a Merchant Rule match into a vote over the ensemble's categories.

    The rule's confidence goes to its own category; the rest is spread evenly
    over the others, so the vote is a probability vector like the models'.

    Args:
        rule: The matched rule, exact or partial, or None.
        class_ids: The ensemble's category ids, in column order.

    Returns:
        The vote, or None when no rule matched or the rule points at a category
        the ensemble was never trained on.
    """
    if rule is None or rule.category_id not in class_ids:
        return None
    others = len(class_ids) - 1
    if others == 0:
        return np.ones(1)
    vote = np.full(len(class_ids), (1.0 - rule.confidence) / others)
    vote[class_ids.index(rule.category_id)] = rule.confidence
    return vote


def rule_votes(
    rule_set: MerchantRuleSet, transactions: list[TransactionInput], class_ids: list[int]
) -> tuple[list[MerchantMapping | None], np.ndarray, np.ndarray]:
    """Score every transaction against a set of Merchant Rules.

    Args:
        rule_set: The rules to match against.
        transactions: Transactions to score, in order.
        class_ids: The ensemble's category ids, in column order.

    Returns:
        The matched rule per transaction (None where none matched), the vote
        matrix (all-zero rows where none matched), and a mask of the rows a
        rule voted on.
    """
    matches = [rule_set.get_category(txn.name) for txn in transactions]
    votes = np.zeros((len(transactions), len(class_ids)))
    voted = np.zeros(len(transactions), dtype=bool)
    for i, rule in enumerate(matches):
        vector = rule_probability_vector(rule, class_ids)
        if vector is not None:
            votes[i] = vector
            voted[i] = True
    return matches, votes, voted


def blend_probabilities(
    lgbm_probs: np.ndarray,
    nb_probs: np.ndarray,
    rule_probs: np.ndarray,
    has_rule: np.ndarray,
    weights: dict[str, float],
) -> np.ndarray:
    """Blend the three voters row by row.

    Rows without a Merchant Rule are renormalised over the two models: the rule
    weight is redistributed between LightGBM and Naive Bayes in proportion to
    their own weights. A merchant without a rule therefore gets exactly the
    prediction the two models gave before rules became a voter, instead of one
    damped by a missing third vote.

    Args:
        lgbm_probs: LightGBM probabilities, aligned to the ensemble's classes.
        nb_probs: Naive Bayes probabilities.
        rule_probs: Merchant Rule votes; rows without a rule are ignored.
        has_rule: Mask of the rows a rule voted on.
        weights: ``lgbm``, ``nb``, and ``rule`` weights summing to 1.

    Returns:
        Blended probabilities of the same shape as the inputs.
    """
    w_lgbm, w_nb, w_rule = weights["lgbm"], weights["nb"], weights.get("rule", 0.0)
    blended = w_lgbm * lgbm_probs + w_nb * nb_probs + w_rule * rule_probs
    model_weight = w_lgbm + w_nb
    no_rule = ~has_rule
    if model_weight > 0 and no_rule.any():
        blended[no_rule] = (w_lgbm * lgbm_probs[no_rule] + w_nb * nb_probs[no_rule]) / model_weight
    return blended


class EnsembleCategorizer:
    """Ensemble categorizer blending LightGBM, Naive Bayes, and the Merchant Rules."""

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
        self.ensemble_weights = dict(DEFAULT_WEIGHTS)
        self.is_trained = False
        self.cv_results: dict[str, Any] | None = None
        self.model_version = "1.0-ensemble"
        self.model_id = "untrained"

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

    @staticmethod
    def _training_split_rules(transactions: list[TransactionInput], labels: np.ndarray) -> MerchantRuleSet:
        """Derive Merchant Rules from the training split alone.

        The rules stored in the database come from every reviewed transaction,
        validation rows included. Scoring the validation split with those would
        let a rule grade the very transactions it was built from, so weight
        optimisation derives its own rules in memory. These rules see every
        labelled training transaction, not only the reviewed ones, which is the
        closest stand-in available at this point in training.

        Args:
            transactions: The training split.
            labels: Their category ids, in the same order.

        Returns:
            A rule set matching merchants exactly like the stored rules do.
        """
        reviews = [(txn.name, int(label), txn.date) for txn, label in zip(transactions, labels, strict=True)]
        return MerchantRuleSet.from_derived(derive_rules(reviews))

    def train_with_validation_optimization(
        self, progress_callback: Callable[[str], None] | None = None
    ) -> dict[str, Any]:
        """Train the ensemble and learn the weight of each voter on a validation split.

        Grid-searches the LightGBM, Naive Bayes, and Merchant Rule weights over
        a simplex and keeps the combination with the best validation accuracy.

        Args:
            progress_callback: Optional callback for progress updates. Called with phase name
                              (e.g., "training_nb", "optimizing_weights").

        Returns:
            The chosen weights, the validation accuracy, and the sample counts.
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

        class_ids = [int(c) for c in nb_temp.classes_]
        _, rule_val_votes, val_has_rule = rule_votes(
            self._training_split_rules(train_transactions, train_labels), val_transactions, class_ids
        )
        print(f"  Merchant rules matched {int(val_has_rule.sum())}/{len(val_transactions)} validation transactions")

        from sklearn.metrics import accuracy_score

        weight_candidates = weight_grid()
        scored: list[tuple[float, dict[str, float]]] = []
        for weights in weight_candidates:
            ensemble_probas = blend_probabilities(lgbm_val_probas, nb_val_probas, rule_val_votes, val_has_rule, weights)
            ensemble_predictions = nb_temp.label_encoder.inverse_transform(np.argmax(ensemble_probas, axis=1))
            scored.append((float(accuracy_score(val_labels, ensemble_predictions)), weights))

        # Ties go to the smallest rule weight: prefer the ensemble that leans on the models.
        scored.sort(key=lambda pair: (-pair[0], pair[1]["rule"]))
        for score, weights in scored[:5]:
            print(f"  LightGBM={weights['lgbm']:.1f}, NB={weights['nb']:.1f}, rule={weights['rule']:.1f}: {score:.4f}")
        best_score, best_weights = scored[0]

        print(
            f"🎯 Best weights: LightGBM={best_weights['lgbm']:.1f}, NB={best_weights['nb']:.1f}, "
            f"rule={best_weights['rule']:.1f} (accuracy: {best_score:.4f})"
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
            "top_weight_candidates": [{"weights": w, "accuracy": s} for s, w in scored[:5]],
            "n_weight_candidates": len(weight_candidates),
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
        """Predict categories by blending LightGBM, Naive Bayes, and the Merchant Rules.

        All three voters score every transaction in one batch and their votes
        are blended with the learned weights. A rule never decides on its own:
        it can only pull the blend towards its category, and the models can
        outvote it. Transactions whose merchant has no rule are scored by the
        two models renormalised, so they predict exactly as before rules
        joined the ensemble. Every voter's probabilities are recorded for the
        Audit Trail.
        """
        if not self.is_trained:
            raise ValueError("Ensemble must be trained before prediction")
        if not transactions:
            return []

        # Reviews and propagations write rules between imports; this
        # long-lived singleton would otherwise keep a stale rule cache.
        self.lgbm_component.merchant_mapper.reload()

        nb_classes = self.nb_component.classes_
        assert nb_classes is not None, "NB component must be trained before prediction"
        lgbm_probas = self._align_probas(
            self.lgbm_component.predict_proba(transactions), self.lgbm_component.classes_, nb_classes
        )
        nb_probas = self.nb_component.predict_proba(transactions)
        class_ids = [int(c) for c in nb_classes]
        rules, rule_probas, has_rule = rule_votes(self.lgbm_component.merchant_mapper.rule_set, transactions, class_ids)
        combined = blend_probabilities(lgbm_probas, nb_probas, rule_probas, has_rule, self.ensemble_weights)

        lgbm_weight, nb_weight = self.ensemble_weights["lgbm"], self.ensemble_weights["nb"]
        rule_weight = self.ensemble_weights.get("rule", 0.0)

        predictions: list[TransactionPrediction] = []
        for i, txn in enumerate(transactions):
            rule = rules[i]
            detail = PredictionDetail(
                source="ensemble",
                rule_pattern=rule.merchant_pattern if rule else None,
                rule_category_id=rule.category_id if rule else None,
                rule_confidence=rule.confidence if rule else None,
                lgbm_probs=probs_by_category(class_ids, lgbm_probas[i]),
                nb_probs=probs_by_category(class_ids, nb_probas[i]),
                rule_probs=probs_by_category(class_ids, rule_probas[i]) if has_rule[i] else {},
                ensemble_probs=probs_by_category(class_ids, combined[i]),
                lgbm_weight=lgbm_weight,
                nb_weight=nb_weight,
                rule_weight=rule_weight if has_rule[i] else 0.0,
            )
            pred_idx = int(np.argmax(combined[i]))
            predictions.append(
                TransactionPrediction(
                    transaction_id=txn.generate_id(),
                    predicted_category_id=class_ids[pred_idx],
                    confidence_score=float(combined[i][pred_idx]),
                    feature_contributions=self._combine_feature_contributions(
                        lgbm_probas[i], nb_probas[i], bool(has_rule[i])
                    ),
                    detail=detail,
                )
            )

        return predictions

    def _combine_feature_contributions(
        self, lgbm_probas: np.ndarray, nb_probas: np.ndarray, has_rule: bool
    ) -> dict[str, float]:
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
        contributions["ensemble_rule_weight"] = self.ensemble_weights.get("rule", 0.0) if has_rule else 0.0

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
            "char_vectorizer": self.lgbm_component.char_vectorizer,
            "word_vectorizer": self.lgbm_component.word_vectorizer,
            "svd": self.lgbm_component.svd,
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
        self.model_id = model_fingerprint(model_path)

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
            self.lgbm_component.label_encoder = lgbm_data["label_encoder"]
            self.lgbm_component.feature_names = lgbm_data["feature_names"]
            self.lgbm_component.classes_ = lgbm_data["classes_"]
            self.lgbm_component.model_version = lgbm_data["model_version"]
            self.lgbm_component.is_trained = True
            # Load vectorizers with backward compat for old pickles
            self.lgbm_component.char_vectorizer = lgbm_data.get("char_vectorizer", lgbm_data.get("text_vectorizer"))
            self.lgbm_component.word_vectorizer = lgbm_data.get("word_vectorizer", None)
            self.lgbm_component.svd = lgbm_data.get("svd", None)
        else:
            # Old format - direct assignment (legacy support)
            self.lgbm_component = ensemble_data["lgbm_component"]

        self.nb_component = ensemble_data["nb_component"]
        self.ensemble_weights = normalize_weights(ensemble_data["ensemble_weights"])
        self.cv_results = ensemble_data["cv_results"]
        self.model_version = ensemble_data["model_version"]
        self.model_id = model_fingerprint(model_path)

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
