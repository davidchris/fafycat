#!/usr/bin/env python3
"""Establish honest ML baseline metrics after P0 bug fixes.

Connects to prod DB, exports human-reviewed transactions to parquet,
runs 5x5 repeated stratified k-fold CV, evaluates LightGBM (solo),
Naive Bayes (solo), and Ensemble (with per-fold weight optimization),
writes full metrics suite to JSON.
"""

import json
import os
import sys
import warnings
from datetime import date
from math import sqrt
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import (
    brier_score_loss,
    f1_score,
    log_loss,
    precision_recall_fscore_support,
)
from sklearn.model_selection import RepeatedStratifiedKFold, train_test_split

# Set production environment
os.environ["FAFYCAT_DB_URL"] = "sqlite:///data/fafycat_prod.db"
os.environ["FAFYCAT_ENV"] = "production"

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.fafycat.core.config import AppConfig, MLConfig
from src.fafycat.core.database import CategoryORM, DatabaseManager, TransactionORM
from src.fafycat.core.models import TransactionInput
from src.fafycat.ml.categorizer import TransactionCategorizer
from src.fafycat.ml.naive_bayes_classifier import NaiveBayesTextClassifier

# Suppress noisy warnings during CV (75+ model fits produce thousands of repeated warnings)
warnings.filterwarnings("ignore", category=UserWarning, module="lightgbm")
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")
warnings.filterwarnings("ignore", category=FutureWarning, module="sklearn")


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 95% confidence interval for a proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = z * sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def compute_ece(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 8) -> float:
    """Expected Calibration Error with equal-width bins."""
    confidences = np.max(y_prob, axis=1)
    predictions = np.argmax(y_prob, axis=1)
    accuracies = (predictions == y_true).astype(float)

    bin_boundaries = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        mask = (confidences > bin_boundaries[i]) & (confidences <= bin_boundaries[i + 1])
        if mask.sum() == 0:
            continue
        bin_accuracy = accuracies[mask].mean()
        bin_confidence = confidences[mask].mean()
        ece += mask.sum() / len(y_true) * abs(bin_accuracy - bin_confidence)
    return float(ece)


def compute_brier_multiclass(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    """Multiclass Brier score (one-vs-rest averaged across classes)."""
    n_classes = y_prob.shape[1]
    brier = 0.0
    for c in range(n_classes):
        y_binary = (y_true == c).astype(int)
        brier += brier_score_loss(y_binary, y_prob[:, c])
    return float(brier / n_classes)


def compute_risk_coverage(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    confidences: np.ndarray,
    thresholds: list[float],
) -> dict[str, dict[str, float]]:
    """Risk-coverage at various confidence thresholds."""
    results = {}
    for t in thresholds:
        mask = confidences >= t
        coverage = float(mask.sum() / len(y_true))
        error_rate = float((y_pred[mask] != y_true[mask]).mean()) if mask.sum() > 0 else 0.0
        results[f"{t:.2f}"] = {"coverage": round(coverage, 4), "error_rate": round(error_rate, 4)}
    return results


def align_probas(
    probas: np.ndarray,
    model_classes: np.ndarray | None,
    target_classes: np.ndarray,
) -> np.ndarray:
    """Align probability matrix columns to a shared target class order.

    Fills missing classes with 0 and renormalizes rows.
    """
    if model_classes is None:
        return np.ones((probas.shape[0], len(target_classes))) / len(target_classes)

    n_samples = probas.shape[0]
    n_target = len(target_classes)
    aligned = np.zeros((n_samples, n_target))

    model_class_list = list(model_classes)
    for i, cls in enumerate(target_classes):
        if cls in model_class_list:
            src_idx = model_class_list.index(cls)
            aligned[:, i] = probas[:, src_idx]

    row_sums = aligned.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1  # avoid division by zero
    aligned = aligned / row_sums
    return aligned


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_reviewed_transactions(session) -> tuple[list[TransactionInput], np.ndarray, pd.DataFrame]:
    """Load human-reviewed transactions from DB (excludes auto-approved)."""
    query = session.query(TransactionORM).filter(
        TransactionORM.category_id.isnot(None),
        TransactionORM.is_reviewed.is_(True),
    )
    transactions = query.all()

    if not transactions:
        raise ValueError("No human-reviewed transactions found in the database.")

    # Count per category and filter to >= 5 samples
    min_samples = 5
    category_counts: dict[int, int] = {}
    for txn in transactions:
        cat_id = cast(int, txn.category_id)
        category_counts[cat_id] = category_counts.get(cat_id, 0) + 1

    valid_categories = {cid for cid, count in category_counts.items() if count >= min_samples}

    if len(valid_categories) < 2:
        raise ValueError(f"Need at least 2 categories with {min_samples}+ samples.")

    # Category name lookup
    cat_names: dict[int, str] = {}
    for cat_id in valid_categories:
        cat = session.query(CategoryORM).filter(CategoryORM.id == cat_id).first()
        if cat:
            cat_names[cat_id] = cat.name

    excluded = set(category_counts.keys()) - valid_categories
    if excluded:
        excluded_info = [f"{cat_names.get(c, f'id={c}')} ({category_counts[c]})" for c in sorted(excluded)]
        print(f"Excluding categories with <{min_samples} samples: {', '.join(excluded_info)}")

    # Convert to model inputs
    txn_inputs: list[TransactionInput] = []
    labels: list[int] = []
    rows: list[dict[str, Any]] = []

    for txn in transactions:
        if txn.category_id not in valid_categories:
            continue

        txn_input = TransactionInput(
            date=cast(date, txn.date),
            value_date=cast(date | None, txn.value_date),
            name=str(txn.name),
            purpose=str(txn.purpose or ""),
            amount=cast(float, txn.amount),
            currency=str(txn.currency),
        )
        txn_inputs.append(txn_input)
        labels.append(cast(int, txn.category_id))

        rows.append(
            {
                "id": txn.id,
                "date": str(txn.date),
                "value_date": str(txn.value_date) if txn.value_date else None,
                "name": txn.name,
                "purpose": txn.purpose or "",
                "amount": txn.amount,
                "currency": txn.currency,
                "category_id": txn.category_id,
                "category_name": cat_names.get(cast(int, txn.category_id), ""),
                "is_reviewed": txn.is_reviewed,
            }
        )

    print(f"Loaded {len(txn_inputs)} human-reviewed transactions across {len(valid_categories)} categories")
    for cid in sorted(valid_categories):
        print(f"  {cat_names.get(cid, f'id={cid}')}: {category_counts[cid]} samples")

    return txn_inputs, np.array(labels), pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Model evaluation helpers
# ---------------------------------------------------------------------------


def get_lgbm_probas(categorizer: TransactionCategorizer, test_txns: list[TransactionInput]) -> np.ndarray:
    """Get full probability vectors from a fitted LightGBM categorizer.

    Bypasses merchant mapper — pure ML evaluation.
    """
    features_list = categorizer.feature_extractor.extract_batch_features(test_txns)
    test_df = pd.DataFrame(features_list)
    X_test = categorizer._prepare_features(test_df, fit=False)
    if categorizer.calibrated_classifier is not None:
        return categorizer.calibrated_classifier.predict_proba(X_test)
    return categorizer.classifier.predict_proba(X_test)


def compute_fold_metrics(y_true_enc: np.ndarray, y_prob: np.ndarray, n_classes: int) -> dict[str, float]:
    """Compute metric suite for a single fold."""
    y_pred = np.argmax(y_prob, axis=1)
    return {
        "macro_f1": float(f1_score(y_true_enc, y_pred, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y_true_enc, y_pred, average="weighted", zero_division=0)),
        "log_loss": float(log_loss(y_true_enc, y_prob, labels=list(range(n_classes)))),
        "brier_score": compute_brier_multiclass(y_true_enc, y_prob),
        "ece_8bins": compute_ece(y_true_enc, y_prob, n_bins=8),
    }


def compute_aggregate_metrics(
    fold_scores: list[float],
    all_true: list[np.ndarray],
    all_prob: list[np.ndarray],
    unique_classes: np.ndarray,
    cat_names: dict[int, str],
    thresholds: list[float],
) -> dict[str, Any]:
    """Compute aggregate metrics from all CV folds."""
    y_true = np.concatenate(all_true)
    y_prob = np.concatenate(all_prob)
    y_pred = np.argmax(y_prob, axis=1)
    confidences = np.max(y_prob, axis=1)
    n_classes = len(unique_classes)

    # Aggregate metrics over concatenated predictions
    macro_f1_agg = float(f1_score(y_true, y_pred, average="macro", zero_division=0))
    weighted_f1_agg = float(f1_score(y_true, y_pred, average="weighted", zero_division=0))
    ll = float(log_loss(y_true, y_prob, labels=list(range(n_classes))))
    brier = compute_brier_multiclass(y_true, y_prob)
    ece = compute_ece(y_true, y_prob, n_bins=8)

    # Fold-level stats with Nadeau-Bengio corrected 95% CI
    scores = np.array(fold_scores)
    mean_score = float(scores.mean())
    std_score = float(scores.std(ddof=1))
    n_folds = len(fold_scores)
    # 5x5 CV: test_ratio = 1/5 = 0.2, train_ratio = 4/5 = 0.8
    corrected_se = std_score * sqrt(1 / n_folds + 0.2 / 0.8)
    t_crit = float(stats.t.ppf(0.975, df=n_folds - 1))
    ci_low = mean_score - t_crit * corrected_se
    ci_high = mean_score + t_crit * corrected_se

    # Per-category P/R with Wilson CIs
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=list(range(n_classes)), average=None, zero_division=0
    )

    per_category: dict[str, Any] = {}
    for i, cls in enumerate(unique_classes):
        cat_name = cat_names.get(int(cls), f"category_{cls}")
        sup = int(support[i])

        tp = int(((y_pred == i) & (y_true == i)).sum())
        pred_pos = int((y_pred == i).sum())
        actual_pos = int((y_true == i).sum())

        p_ci = wilson_ci(tp, pred_pos) if pred_pos > 0 else (0.0, 0.0)
        r_ci = wilson_ci(tp, actual_pos) if actual_pos > 0 else (0.0, 0.0)

        per_category[cat_name] = {
            "precision": round(float(precision[i]), 4),
            "recall": round(float(recall[i]), 4),
            "f1": round(float(f1[i]), 4),
            "wilson_ci_p": [round(p_ci[0], 4), round(p_ci[1], 4)],
            "wilson_ci_r": [round(r_ci[0], 4), round(r_ci[1], 4)],
            "support": sup,
        }

    # Risk-coverage curve
    risk_cov = compute_risk_coverage(y_true, y_pred, confidences, thresholds)

    # Auto-approve at 0.95
    auto_mask = confidences >= 0.95
    auto_coverage = float(auto_mask.sum() / len(y_true))
    auto_risk = float((y_pred[auto_mask] != y_true[auto_mask]).mean()) if auto_mask.sum() > 0 else 0.0

    return {
        "macro_f1": {
            "mean": round(mean_score, 4),
            "std": round(std_score, 4),
            "ci_95": [round(ci_low, 4), round(ci_high, 4)],
        },
        "macro_f1_aggregate": round(macro_f1_agg, 4),
        "weighted_f1": round(weighted_f1_agg, 4),
        "log_loss": round(ll, 4),
        "brier_score": round(brier, 4),
        "ece_8bins": round(ece, 4),
        "per_category": per_category,
        "risk_coverage": risk_cov,
        "auto_approve_0.95": {
            "coverage": round(auto_coverage, 4),
            "selective_risk": round(auto_risk, 4),
        },
        "fold_scores": [round(s, 4) for s in fold_scores],
    }


# ---------------------------------------------------------------------------
# Main CV loop
# ---------------------------------------------------------------------------


def run_cv(
    txn_inputs: list[TransactionInput],
    labels: np.ndarray,
    session,
    config: MLConfig,
    cat_names: dict[int, str],
) -> dict[str, Any]:
    """Run 5x5 repeated stratified k-fold and evaluate all models."""
    rskf = RepeatedStratifiedKFold(n_splits=5, n_repeats=5, random_state=42)
    txn_array = np.array(txn_inputs, dtype=object)

    # Shared class order across all folds
    unique_classes = np.sort(np.unique(labels))
    n_classes = len(unique_classes)
    class_to_idx = {int(c): i for i, c in enumerate(unique_classes)}

    # Per-model accumulators
    accumulators: dict[str, dict[str, list]] = {
        name: {"fold_scores": [], "all_true": [], "all_prob": []} for name in ["lightgbm", "naive_bayes", "ensemble"]
    }

    thresholds = [0.50, 0.60, 0.70, 0.80, 0.85, 0.90, 0.95, 0.99]
    n_total_folds = rskf.get_n_splits()

    for fold_idx, (train_idx, test_idx) in enumerate(rskf.split(txn_array, labels)):
        print(f"\n--- Fold {fold_idx + 1}/{n_total_folds} ---")

        train_txns = txn_array[train_idx].tolist()
        test_txns = txn_array[test_idx].tolist()
        train_labels = labels[train_idx]
        test_labels = labels[test_idx]

        test_encoded = np.array([class_to_idx[int(lbl)] for lbl in test_labels])

        # --- LightGBM (solo) ---
        lgbm = TransactionCategorizer(session, config)
        lgbm.fit(train_txns, train_labels)
        lgbm_probas = get_lgbm_probas(lgbm, test_txns)
        lgbm_aligned = align_probas(lgbm_probas, lgbm.classes_, unique_classes)

        lgbm_m = compute_fold_metrics(test_encoded, lgbm_aligned, n_classes)
        accumulators["lightgbm"]["fold_scores"].append(lgbm_m["macro_f1"])
        accumulators["lightgbm"]["all_true"].append(test_encoded)
        accumulators["lightgbm"]["all_prob"].append(lgbm_aligned)

        # --- Naive Bayes (solo) ---
        nb = NaiveBayesTextClassifier(
            alpha=config.nb_alpha,
            use_complement=config.nb_use_complement,
            max_features=config.nb_max_features,
        )
        nb.fit(train_txns, train_labels)
        nb_probas = nb.predict_proba(test_txns)
        nb_aligned = align_probas(nb_probas, nb.classes_, unique_classes)

        nb_m = compute_fold_metrics(test_encoded, nb_aligned, n_classes)
        accumulators["naive_bayes"]["fold_scores"].append(nb_m["macro_f1"])
        accumulators["naive_bayes"]["all_true"].append(test_encoded)
        accumulators["naive_bayes"]["all_prob"].append(nb_aligned)

        # --- Ensemble (per-fold weight optimization) ---
        ens_probas = _optimize_ensemble_fold(
            train_txns, train_labels, lgbm_aligned, nb_aligned, unique_classes, class_to_idx, session, config, fold_idx
        )

        ens_m = compute_fold_metrics(test_encoded, ens_probas, n_classes)
        accumulators["ensemble"]["fold_scores"].append(ens_m["macro_f1"])
        accumulators["ensemble"]["all_true"].append(test_encoded)
        accumulators["ensemble"]["all_prob"].append(ens_probas)

        print(f"  LGB={lgbm_m['macro_f1']:.3f}  NB={nb_m['macro_f1']:.3f}  ENS={ens_m['macro_f1']:.3f}")

    # Aggregate all models
    results = {}
    for model_name, acc in accumulators.items():
        results[model_name] = compute_aggregate_metrics(
            acc["fold_scores"], acc["all_true"], acc["all_prob"], unique_classes, cat_names, thresholds
        )

    return results


def _optimize_ensemble_fold(
    train_txns: list[TransactionInput],
    train_labels: np.ndarray,
    lgbm_test_aligned: np.ndarray,
    nb_test_aligned: np.ndarray,
    unique_classes: np.ndarray,
    class_to_idx: dict[int, int],
    session,
    config: MLConfig,
    fold_idx: int,
) -> np.ndarray:
    """Optimize ensemble weights on a sub-validation split, then combine test predictions.

    1. Sub-split training data 80/20
    2. Train LightGBM + NB on sub-train
    3. Pick best weight on sub-val (macro F1)
    4. Combine the already-computed full-fold test predictions with best weight
    """
    try:
        sub_train, sub_val, sub_train_y, sub_val_y = train_test_split(
            train_txns, train_labels, test_size=0.2, stratify=train_labels, random_state=42 + fold_idx
        )
    except ValueError:
        # Stratified split impossible (too few samples in some class)
        return 0.7 * lgbm_test_aligned + 0.3 * nb_test_aligned

    sub_val_enc = np.array([class_to_idx[int(lbl)] for lbl in sub_val_y])

    # Train on sub-train
    lgbm_sub = TransactionCategorizer(session, config)
    lgbm_sub.fit(sub_train, sub_train_y)
    lgbm_sub_probas = get_lgbm_probas(lgbm_sub, sub_val)
    lgbm_sub_aligned = align_probas(lgbm_sub_probas, lgbm_sub.classes_, unique_classes)

    nb_sub = NaiveBayesTextClassifier(
        alpha=config.nb_alpha,
        use_complement=config.nb_use_complement,
        max_features=config.nb_max_features,
    )
    nb_sub.fit(sub_train, sub_train_y)
    nb_sub_probas = nb_sub.predict_proba(sub_val)
    nb_sub_aligned = align_probas(nb_sub_probas, nb_sub.classes_, unique_classes)

    # Sweep weights
    best_w = 0.7
    best_score = -1.0
    for w in np.arange(0.3, 0.85, 0.05):
        combined = float(w) * lgbm_sub_aligned + (1 - float(w)) * nb_sub_aligned
        preds = np.argmax(combined, axis=1)
        score = float(f1_score(sub_val_enc, preds, average="macro", zero_division=0))
        if score > best_score:
            best_score = score
            best_w = float(w)

    # Combine full-fold test predictions with optimal weight
    return best_w * lgbm_test_aligned + (1 - best_w) * nb_test_aligned


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Run baseline establishment."""
    print("=" * 60)
    print("Establishing Honest ML Baseline")
    print("=" * 60)

    config = AppConfig()
    config.ensure_dirs()

    # Suppress LightGBM verbosity during CV (75+ fits) and set parallelism
    config.ml.lgbm_params["verbose"] = -1
    config.ml.lgbm_params["n_jobs"] = 8

    db_manager = DatabaseManager(config)

    with db_manager.get_session() as session:
        # Step 1: Load data
        print("\n[1/4] Loading human-reviewed transactions...")
        txn_inputs, labels, df = load_reviewed_transactions(session)

        # Step 2: Save frozen dataset
        parquet_path = Path("data/baseline_dataset_v1.parquet")
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(parquet_path, index=False)
        print(f"\nFrozen dataset saved to {parquet_path}")

        # Category name lookup
        unique_cats = np.unique(labels)
        cat_names: dict[int, str] = {}
        for cid in unique_cats:
            cat = session.query(CategoryORM).filter(CategoryORM.id == int(cid)).first()
            if cat:
                cat_names[int(cid)] = cat.name

        # Step 3: Run 5x5 CV
        print("\n[2/4] Running 5x5 repeated stratified k-fold CV...")
        results = run_cv(txn_inputs, labels, session, config.ml, cat_names)

        # Step 4: Assemble and write output
        print("\n[3/4] Writing results...")
        output = {
            "metadata": {
                "date": str(date.today()),
                "dataset": str(parquet_path),
                "n_transactions": len(txn_inputs),
                "n_categories": len(unique_cats),
                "category_names": {str(k): v for k, v in cat_names.items()},
                "cv_scheme": "5x5 repeated stratified k-fold",
            },
            **results,
        }

        json_path = Path("scratch_pads/baseline_metrics.json")
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(json_path, "w") as f:
            json.dump(output, f, indent=2)

        print(f"Results saved to {json_path}")

        # Step 5: Print summary
        print("\n[4/4] Summary")
        print("=" * 60)
        print(f"Dataset: {len(txn_inputs)} transactions, {len(unique_cats)} categories")
        print("CV: 5x5 repeated stratified k-fold (25 folds)\n")

        for model_name in ["lightgbm", "naive_bayes", "ensemble"]:
            m = results[model_name]
            mf1 = m["macro_f1"]
            aa = m["auto_approve_0.95"]
            print(f"{model_name.upper()}")
            print(
                f"  Macro F1:      {mf1['mean']:.4f} +/- {mf1['std']:.4f}  "
                f"95% CI [{mf1['ci_95'][0]:.4f}, {mf1['ci_95'][1]:.4f}]"
            )
            print(f"  Weighted F1:   {m['weighted_f1']:.4f}")
            print(f"  Log Loss:      {m['log_loss']:.4f}")
            print(f"  Brier Score:   {m['brier_score']:.4f}")
            print(f"  ECE (8 bins):  {m['ece_8bins']:.4f}")
            cov_pct = aa["coverage"] * 100
            risk_pct = aa["selective_risk"] * 100
            print(f"  Auto-approve:  {cov_pct:.1f}% coverage, {risk_pct:.1f}% error rate")
            print()


if __name__ == "__main__":
    main()
