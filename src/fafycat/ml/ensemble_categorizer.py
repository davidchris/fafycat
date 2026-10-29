"""Ensemble categorizer stacking LightGBM, Naive Bayes, and the Merchant Rules.

All three are voters: each one turns a transaction into a probability vector
over the categories. A level-1 model (:class:`~fafycat.ml.stack.StackLR`)
reads the three vectors plus a few meta features and produces the final
probabilities. Everything the stack learns from is out-of-fold: the voters
are refitted on five folds so that no row is judged by a model, or a rule,
that saw it during training.
"""

import json
import pickle
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, cast

import numpy as np
from sklearn.model_selection import StratifiedKFold
from sqlalchemy.orm import Session

from ..core.config import MLConfig
from ..core.database import CategoryORM, ModelMetadataORM, TransactionORM
from ..core.models import MerchantMapping, PredictionDetail, TransactionInput, TransactionPrediction
from .calibration import TemperatureScaler, fold_count
from .categorizer import TransactionCategorizer
from .merchant_mapper import MerchantRuleSet, derive_rules
from .model_identity import model_fingerprint, probs_by_category
from .naive_bayes_classifier import NaiveBayesTextClassifier
from .stack import META_NAMES, StackLR, Voters, lookup_seen, meta_features, seen_counts

OOF_SEED = 0
"""Shuffle seed of the out-of-fold split; fixed so retrains are comparable."""

MODEL_VERSION = "2.0-stack"
"""Format of the saved ensemble; a file with any other version must be retrained."""


class IncompatibleModelError(Exception):
    """The saved model file exists, but this version of FafyCat cannot load it."""


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


def _rule_confidences(matches: list[MerchantMapping | None], voted: np.ndarray) -> np.ndarray:
    """Confidence of the rule that voted on each row, 0 where none did."""
    return np.array(
        [m.confidence if (m is not None and hit) else 0.0 for m, hit in zip(matches, voted, strict=True)],
        dtype=float,
    )


class EnsembleCategorizer:
    """Ensemble categorizer blending LightGBM, Naive Bayes, and the Merchant Rules."""

    def __init__(self, session: Session, config: MLConfig) -> None:
        self.session = session
        self.config = config

        # Level 0: the voters
        self.lgbm_component = TransactionCategorizer(session, config)
        self.nb_component = self._new_nb()
        self.nb_temperature: TemperatureScaler | None = None
        """Naive Bayes is under-confident on its own; this is fitted on out-of-fold rows."""
        self.seen_counts: dict[str, int] = {}
        """Training rows per cleaned merchant pattern, for the ``seen_log`` meta feature."""

        # Level 1
        self.stack: StackLR | None = None
        self.n_folds = config.ensemble_cv_folds

        self.is_trained = False
        self.classes_: np.ndarray | None = None
        self.training_summary: dict[str, Any] | None = None
        self.model_version = MODEL_VERSION
        self.model_id = "untrained"

    def _new_nb(self) -> NaiveBayesTextClassifier:
        return NaiveBayesTextClassifier(
            alpha=self.config.nb_alpha,
            use_complement=self.config.nb_use_complement,
            max_features=self.config.nb_max_features,
        )

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
        min_samples_per_category = max(5, self.n_folds)  # every class must reach every fold

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

    def train(self, progress_callback: Callable[[str], None] | None = None) -> dict[str, Any]:
        """Train the voters and the stack that combines them.

        Five stratified folds produce out-of-fold outputs of every voter for
        every training row. Those fit the two temperatures and the stack.
        The final voters are then fitted on all rows and carry the
        temperatures learned from the folds.

        Args:
            progress_callback: Called with ``training_folds``, ``fitting_stack``
                and ``training_final`` as each phase starts.

        Returns:
            The training summary: out-of-fold accuracy and log-loss of the
            stack, its auto-approve rate and error at the configured threshold,
            the temperatures, and the sample counts.
        """

        def progress(phase: str) -> None:
            if progress_callback:
                progress_callback(phase)

        print("🔍 Preparing training data for ensemble...")
        transactions, labels = self.prepare_training_data()
        classes = np.unique(labels)
        class_ids = [int(c) for c in classes]
        y = np.searchsorted(classes, labels)
        print(f"📝 Training stacked ensemble on {len(transactions)} transactions, {len(classes)} categories...")

        progress("training_folds")
        oof = self._out_of_fold_voters(transactions, labels, y, class_ids)

        progress("fitting_stack")
        print("🎚️ Fitting temperatures on out-of-fold predictions...")
        lgbm_temperature = TemperatureScaler().fit(oof.lgbm, y)
        self.nb_temperature = TemperatureScaler().fit(oof.nb, y)
        oof = self._scale(oof, lgbm_temperature)
        print(f"  LightGBM T={lgbm_temperature.temperature_:.2f}, Naive Bayes T={self.nb_temperature.temperature_:.2f}")

        print("🧠 Fitting the stack...")
        self.stack = StackLR(c=self.config.stack_l2_c).fit(oof, y, len(classes))
        self.training_summary = self._summarise(oof, y, len(classes))
        self.training_summary.update(
            {
                "temperature_lgbm": lgbm_temperature.temperature_,
                "temperature_nb": self.nb_temperature.temperature_,
                "n_training_samples": len(transactions),
                "n_classes": len(classes),
                "n_folds": fold_count(y, self.n_folds),
                "stack_importance": self.stack.block_importance(),
            }
        )
        summary = self.training_summary
        print(
            f"  Out-of-fold accuracy {summary['oof_accuracy']:.3f}, log-loss {summary['oof_logloss']:.3f}; "
            f"at {summary['auto_threshold']:.2f}: {summary['auto_rate']:.1%} auto-approved, "
            f"{summary['auto_error_rate']:.2%} of those wrong"
        )

        progress("training_final")
        print("🚀 Training final voters on all rows...")
        self.lgbm_component.fit(transactions, labels, calibrate=False)
        self.lgbm_component.calibrator = lgbm_temperature
        self.nb_component = self._new_nb()
        self.nb_component.fit(transactions, labels)
        self.seen_counts = seen_counts(transactions)

        print("🏪 Updating merchant mappings...")
        self.lgbm_component.merchant_mapper.update_from_transactions()

        self._save_ensemble_metadata()
        self.is_trained = True
        self.classes_ = classes
        print(f"✅ Ensemble training complete! Out-of-fold accuracy: {summary['oof_accuracy']:.3f}")
        return summary

    def _out_of_fold_voters(
        self, transactions: list[TransactionInput], labels: np.ndarray, y: np.ndarray, class_ids: list[int]
    ) -> Voters:
        """Score every training row with voters that never saw it.

        Within each fold LightGBM and Naive Bayes are fitted on the other
        folds and the Merchant Rules are derived from those folds alone;
        rules from all rows would let a rule grade the row it was built from.
        """
        n, k = len(y), len(class_ids)
        oof = Voters(
            lgbm=np.zeros((n, k)),
            nb=np.zeros((n, k)),
            rule_vote=np.zeros((n, k)),
            rule_hit=np.zeros(n, dtype=bool),
            rule_conf=np.zeros(n),
            seen=np.zeros(n),
            amount=np.array([t.amount for t in transactions], dtype=float),
        )
        n_folds = fold_count(y, self.n_folds)
        folds = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=OOF_SEED)
        for fold, (train_idx, test_idx) in enumerate(folds.split(np.zeros(n), y), start=1):
            print(f"  Fold {fold}/{n_folds}: fitting voters on {len(train_idx)} rows...")
            fold_txns = [transactions[i] for i in train_idx]
            fold_labels = labels[train_idx]
            held_out = [transactions[i] for i in test_idx]

            lgbm = TransactionCategorizer(self.session, self.config)
            lgbm.fit(fold_txns, fold_labels, calibrate=False)
            oof.lgbm[test_idx] = self._align_probas(lgbm.predict_proba(held_out), lgbm.classes_, class_ids)

            nb = self._new_nb()
            nb.fit(fold_txns, fold_labels)
            oof.nb[test_idx] = self._align_probas(nb.predict_proba(held_out), nb.classes_, class_ids)

            rules = self._training_split_rules(fold_txns, fold_labels)
            matches, votes, voted = rule_votes(rules, held_out, class_ids)
            oof.rule_vote[test_idx], oof.rule_hit[test_idx] = votes, voted
            oof.rule_conf[test_idx] = _rule_confidences(matches, voted)
            oof.seen[test_idx] = lookup_seen(seen_counts(fold_txns), held_out)
        return oof

    def _scale(self, v: Voters, lgbm_temperature: TemperatureScaler) -> Voters:
        """Apply the two temperatures to the model voters; the rule vote is hand-made."""
        assert self.nb_temperature is not None
        return Voters(
            lgbm=lgbm_temperature.predict_proba(v.lgbm),
            nb=self.nb_temperature.predict_proba(v.nb),
            rule_vote=v.rule_vote,
            rule_hit=v.rule_hit,
            rule_conf=v.rule_conf,
            seen=v.seen,
            amount=v.amount,
        )

    def _summarise(self, oof: Voters, y: np.ndarray, n_classes: int) -> dict[str, Any]:
        """Judge the stack on its own out-of-fold predictions over the out-of-fold voters.

        Scoring the stack in-sample would repeat, one level up, the mistake
        of calibrating a model on its own training rows.
        """
        n_folds = fold_count(y, self.n_folds)
        folds = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=OOF_SEED + 1)
        probs = np.zeros((len(y), n_classes))
        for train_idx, test_idx in folds.split(np.zeros(len(y)), y):
            model = StackLR(c=self.config.stack_l2_c).fit(oof.subset(train_idx), y[train_idx], n_classes)
            probs[test_idx] = model.predict_proba(oof.subset(test_idx))
        rows = np.arange(len(y))
        correct = probs.argmax(axis=1) == y
        confidence = probs.max(axis=1)
        threshold = self.config.auto_approve_threshold
        auto = confidence >= threshold
        return {
            "oof_accuracy": float(correct.mean()),
            "oof_logloss": float(-np.log(np.clip(probs[rows, y], 1e-12, 1.0)).mean()),
            "auto_threshold": threshold,
            "auto_rate": float(auto.mean()),
            "auto_error_rate": float((auto & ~correct).sum() / auto.sum()) if auto.any() else 0.0,
        }

    @staticmethod
    def _align_probas(probas: np.ndarray, source_classes: np.ndarray | None, class_ids: list[int]) -> np.ndarray:
        """Move probability columns from a voter's class order to the ensemble's.

        Args:
            probas: Probability matrix of shape (n_samples, n_source_classes).
            source_classes: Class labels corresponding to columns of probas.
            class_ids: The ensemble's category ids, in column order.

        Returns:
            Aligned probabilities of shape (n_samples, len(class_ids)); rows are
            renormalised so a voter that never saw a class still sums to 1.
        """
        if source_classes is None:
            return np.full((probas.shape[0], len(class_ids)), 1.0 / len(class_ids))
        aligned = np.zeros((probas.shape[0], len(class_ids)))
        position = {cls: i for i, cls in enumerate(class_ids)}
        for j, cls in enumerate(source_classes):
            if int(cls) in position:
                aligned[:, position[int(cls)]] = probas[:, j]
        row_sums = aligned.sum(axis=1, keepdims=True)
        row_sums[row_sums == 0] = 1
        return aligned / row_sums

    def predict_with_confidence(self, transactions: list[TransactionInput]) -> list[TransactionPrediction]:
        """Predict categories by stacking LightGBM, Naive Bayes, and the Merchant Rules.

        All three voters score every transaction in one batch; the stack
        turns their votes and the meta features into the final probabilities.
        A rule never decides on its own. Every voter's probabilities and the
        meta features are recorded for the Audit Trail.
        """
        if not self.is_trained:
            raise ValueError("Ensemble must be trained before prediction")
        if self.stack is None or self.nb_temperature is None or self.classes_ is None:
            raise ValueError("Ensemble has no stack; retrain the model")
        if not transactions:
            return []

        # Reviews and propagations write rules between imports; this
        # long-lived singleton would otherwise keep a stale rule cache.
        self.lgbm_component.merchant_mapper.reload()

        class_ids = [int(c) for c in self.classes_]
        lgbm_probas = self._align_probas(
            self.lgbm_component.predict_proba(transactions), self.lgbm_component.classes_, class_ids
        )
        nb_probas = self.nb_temperature.predict_proba(
            self._align_probas(self.nb_component.predict_proba(transactions), self.nb_component.classes_, class_ids)
        )
        rules, rule_probas, has_rule = rule_votes(self.lgbm_component.merchant_mapper.rule_set, transactions, class_ids)
        voters = Voters(
            lgbm=lgbm_probas,
            nb=nb_probas,
            rule_vote=rule_probas,
            rule_hit=has_rule,
            rule_conf=_rule_confidences(rules, has_rule),
            seen=lookup_seen(self.seen_counts, transactions),
            amount=np.array([t.amount for t in transactions], dtype=float),
        )
        combined = self.stack.predict_proba(voters)
        meta = meta_features(voters)

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
                meta_features={name: float(value) for name, value in zip(META_NAMES, meta[i], strict=True)},
            )
            pred_idx = int(np.argmax(combined[i]))
            predictions.append(
                TransactionPrediction(
                    transaction_id=txn.generate_id(),
                    predicted_category_id=class_ids[pred_idx],
                    confidence_score=float(combined[i][pred_idx]),
                    feature_contributions=self._feature_contributions(nb_probas[i]),
                    detail=detail,
                )
            )

        return predictions

    def _feature_contributions(self, nb_probas: np.ndarray) -> dict[str, float]:
        """LightGBM's top global importances plus Naive Bayes' confidence, for the explanation view."""
        contributions: dict[str, float] = {}
        classifier = self.lgbm_component.classifier
        if hasattr(classifier, "feature_importances_"):
            importances = classifier.feature_importances_
            top_indices = np.argsort(importances)[-5:]
            total = float(importances[top_indices].sum()) or 1.0
            for idx in top_indices:
                if idx < len(self.lgbm_component.feature_names):
                    contributions[f"lgbm_{self.lgbm_component.feature_names[idx]}"] = float(importances[idx]) / total
        contributions["nb_text_features"] = float(np.max(nb_probas))
        return contributions

    def _save_ensemble_metadata(self) -> None:
        """Save ensemble model metadata to database."""
        # Deactivate previous models
        self.session.query(ModelMetadataORM).update({"is_active": False})

        # Create ensemble metadata
        summary = self.training_summary or {}
        metadata = ModelMetadataORM(
            model_version=self.model_version,
            accuracy=summary.get("oof_accuracy", 0.0),
            feature_importance=json.dumps({"training_summary": summary}),
            parameters=json.dumps(
                {
                    "lgbm_params": self.config.lgbm_params,
                    "nb_alpha": self.config.nb_alpha,
                    "nb_use_complement": self.config.nb_use_complement,
                    "nb_max_features": self.config.nb_max_features,
                    "cv_folds": self.config.ensemble_cv_folds,
                    "stack_l2_c": self.config.stack_l2_c,
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
            "calibrator": self.lgbm_component.calibrator,
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
            "nb_temperature": self.nb_temperature,
            "stack": self.stack,
            "seen_counts": self.seen_counts,
            "classes_": self.classes_,
            "training_summary": self.training_summary,
            "model_version": self.model_version,
            "config": self.config.model_dump(),
        }

        with open(model_path, "wb") as f:
            pickle.dump(ensemble_data, f)
        self.model_id = model_fingerprint(model_path)

    def load_model(self, model_path: Path) -> None:
        """Load trained ensemble model from disk.

        Raises:
            IncompatibleModelError: The file was saved in another model format,
                by a FafyCat version this one cannot read.
        """
        retrain = "Retrain the model on the Settings page."
        try:
            with open(model_path, "rb") as f:
                ensemble_data = pickle.load(f)
        except (pickle.UnpicklingError, ImportError, AttributeError, EOFError) as e:
            raise IncompatibleModelError(f"The saved model cannot be read by this version ({e}). {retrain}") from e

        version = ensemble_data.get("model_version") if isinstance(ensemble_data, dict) else None
        if version != MODEL_VERSION:
            raise IncompatibleModelError(
                f"The saved model has format {version!r}, but this version needs {MODEL_VERSION!r}. {retrain}"
            )
        try:
            self._restore(ensemble_data)
        except KeyError as e:
            raise IncompatibleModelError(f"The saved model is missing {e}. {retrain}") from e
        self.model_id = model_fingerprint(model_path)
        self.is_trained = True

    def _restore(self, ensemble_data: dict[str, Any]) -> None:
        """Copy the saved components onto this ensemble."""
        lgbm_data = ensemble_data["lgbm_model_data"]
        self.lgbm_component = TransactionCategorizer(self.session, self.config)
        self.lgbm_component.classifier = lgbm_data["classifier"]
        self.lgbm_component.calibrator = lgbm_data["calibrator"]
        self.lgbm_component.label_encoder = lgbm_data["label_encoder"]
        self.lgbm_component.feature_names = lgbm_data["feature_names"]
        self.lgbm_component.classes_ = lgbm_data["classes_"]
        self.lgbm_component.model_version = lgbm_data["model_version"]
        self.lgbm_component.char_vectorizer = lgbm_data["char_vectorizer"]
        self.lgbm_component.word_vectorizer = lgbm_data["word_vectorizer"]
        self.lgbm_component.svd = lgbm_data["svd"]
        self.lgbm_component.is_trained = True

        self.nb_component = ensemble_data["nb_component"]
        self.nb_temperature = ensemble_data["nb_temperature"]
        self.stack = ensemble_data["stack"]
        self.seen_counts = ensemble_data["seen_counts"]
        self.classes_ = ensemble_data["classes_"]
        self.training_summary = ensemble_data["training_summary"]
        self.model_version = ensemble_data["model_version"]

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
            "lgbm_explanation": lgbm_explanation,
            "nb_explanation": nb_explanation,
            "training_summary": self.training_summary or {},
        }
