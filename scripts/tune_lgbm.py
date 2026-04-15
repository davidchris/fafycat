#!/usr/bin/env python3
"""Optuna hyperparameter tuning for LightGBM categorizer.

Precomputes TF-IDF+SVD features per fold, then tunes only LightGBM params.
Uses early stopping to auto-tune n_estimators. Validates best params with 5x5 CV.

Usage: uv run --group experiments scripts/tune_lgbm.py
"""

import json
import os
import sys
import time
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import optuna
import pandas as pd
from lightgbm import LGBMClassifier, early_stopping
from scipy.sparse import hstack as sparse_hstack
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import f1_score
from sklearn.model_selection import RepeatedStratifiedKFold, StratifiedKFold, train_test_split
from sklearn.preprocessing import LabelEncoder

# Set production environment
os.environ["FAFYCAT_DB_URL"] = "sqlite:///data/fafycat_prod.db"
os.environ["FAFYCAT_ENV"] = "production"

sys.path.insert(0, str(Path(__file__).parent.parent))

from fafycat.core.config import AppConfig, MLConfig
from fafycat.core.database import DatabaseManager, TransactionORM
from fafycat.core.models import TransactionInput
from fafycat.ml.feature_extractor import FeatureExtractor

warnings.filterwarnings("ignore", category=UserWarning, module="lightgbm")
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")
warnings.filterwarnings("ignore", category=FutureWarning, module="sklearn")


# ---------------------------------------------------------------------------
# Data loading (reused pattern from establish_baseline.py)
# ---------------------------------------------------------------------------


def load_data(session) -> tuple[list[TransactionInput], np.ndarray]:
    """Load human-reviewed transactions from DB."""
    from datetime import date
    from typing import cast

    query = session.query(TransactionORM).filter(
        TransactionORM.category_id.isnot(None),
        TransactionORM.is_reviewed.is_(True),
    )
    transactions = query.all()

    if not transactions:
        raise ValueError("No human-reviewed transactions found.")

    min_samples = 5
    category_counts: dict[int, int] = {}
    for txn in transactions:
        cat_id = cast(int, txn.category_id)
        category_counts[cat_id] = category_counts.get(cat_id, 0) + 1

    valid_categories = {cid for cid, count in category_counts.items() if count >= min_samples}
    if len(valid_categories) < 2:
        raise ValueError(f"Need at least 2 categories with {min_samples}+ samples.")

    txn_inputs: list[TransactionInput] = []
    labels: list[int] = []
    for txn in transactions:
        if txn.category_id not in valid_categories:
            continue
        txn_inputs.append(
            TransactionInput(
                date=cast(date, txn.date),
                value_date=cast(date | None, txn.value_date),
                name=str(txn.name),
                purpose=str(txn.purpose or ""),
                amount=cast(float, txn.amount),
                currency=str(txn.currency),
            )
        )
        labels.append(cast(int, txn.category_id))

    print(f"Loaded {len(txn_inputs)} transactions across {len(valid_categories)} categories")
    return txn_inputs, np.array(labels)


# ---------------------------------------------------------------------------
# Feature precomputation
# ---------------------------------------------------------------------------


def extract_raw_features(txn_inputs: list[TransactionInput], config: MLConfig) -> pd.DataFrame:
    """Extract raw features (numerical + text) for all transactions."""
    extractor = FeatureExtractor()
    features_list = extractor.extract_batch_features(txn_inputs)
    return pd.DataFrame(features_list)


def prepare_features_for_fold(
    X_df_train: pd.DataFrame,
    X_df_val: pd.DataFrame,
    config: MLConfig,
) -> tuple[np.ndarray, np.ndarray]:
    """Fit TF-IDF+SVD on train, transform both train and val. Returns dense arrays."""
    extractor = FeatureExtractor()
    numerical_features = extractor.get_numerical_feature_names()

    X_num_train = X_df_train[numerical_features].fillna(0).values
    X_num_val = X_df_val[numerical_features].fillna(0).values

    text_train = X_df_train["text_combined"].fillna("").values
    text_val = X_df_val["text_combined"].fillna("").values

    char_vec = TfidfVectorizer(**config.tfidf_char_params)
    word_vec = TfidfVectorizer(**config.tfidf_word_params)
    svd = TruncatedSVD(n_components=config.svd_n_components, random_state=42)

    X_char_train = char_vec.fit_transform(text_train)
    X_word_train = word_vec.fit_transform(text_train)
    X_text_train = svd.fit_transform(sparse_hstack([X_char_train, X_word_train]))

    X_char_val = char_vec.transform(text_val)
    X_word_val = word_vec.transform(text_val)
    X_text_val = svd.transform(sparse_hstack([X_char_val, X_word_val]))

    X_train = np.hstack([X_num_train, X_text_train])
    X_val = np.hstack([X_num_val, X_text_val])

    return X_train, X_val


def precompute_folds(
    X_df: pd.DataFrame,
    labels: np.ndarray,
    config: MLConfig,
    n_splits: int = 5,
) -> list[dict[str, Any]]:
    """Precompute TF-IDF+SVD features for each CV fold.

    Returns list of dicts with X_train, X_val, y_train, y_val arrays.
    """
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    le = LabelEncoder()
    y_encoded = le.fit_transform(labels)

    folds = []
    for fold_idx, (train_idx, val_idx) in enumerate(skf.split(X_df, y_encoded)):
        print(f"  Precomputing fold {fold_idx + 1}/{n_splits}...")
        X_df_train = X_df.iloc[train_idx]
        X_df_val = X_df.iloc[val_idx]
        y_train = y_encoded[train_idx]
        y_val = y_encoded[val_idx]

        X_train, X_val = prepare_features_for_fold(X_df_train, X_df_val, config)

        folds.append(
            {
                "X_train": X_train,
                "X_val": X_val,
                "y_train": y_train,
                "y_val": y_val,
            }
        )

    return folds


# ---------------------------------------------------------------------------
# Optuna objective
# ---------------------------------------------------------------------------


def create_objective(
    folds: list[dict[str, Any]],
) -> Any:
    """Create an Optuna objective function with precomputed fold data."""

    def objective(trial: optuna.Trial) -> float:
        params = {
            "num_leaves": trial.suggest_int("num_leaves", 8, 128),
            "max_depth": trial.suggest_int("max_depth", 3, 12),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "feature_fraction": trial.suggest_float("feature_fraction", 0.4, 1.0),
            "bagging_fraction": trial.suggest_float("bagging_fraction", 0.4, 1.0),
            "bagging_freq": trial.suggest_int("bagging_freq", 1, 10),
            "min_child_samples": trial.suggest_int("min_child_samples", 5, 100),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
            # Fixed params
            "n_estimators": 1000,
            "class_weight": "balanced",
            "random_state": 42,
            "n_jobs": -1,
            "verbose": -1,
        }

        fold_scores = []
        for fold_idx, fold in enumerate(folds):
            X_train = fold["X_train"]
            X_val = fold["X_val"]
            y_train = fold["y_train"]
            y_val = fold["y_val"]

            # Sub-split train for early stopping eval set (80/20)
            X_fit, X_es, y_fit, y_es = train_test_split(
                X_train,
                y_train,
                test_size=0.2,
                stratify=y_train,
                random_state=42,
            )

            clf = LGBMClassifier(**params)
            clf.fit(
                X_fit,
                y_fit,
                eval_set=[(X_es, y_es)],
                callbacks=[early_stopping(50, verbose=False)],
            )

            y_pred = clf.predict(X_val)
            score = float(f1_score(y_val, y_pred, average="macro", zero_division=0))
            fold_scores.append(score)

            # Report intermediate result for pruning
            trial.report(np.mean(fold_scores), fold_idx)
            if trial.should_prune():
                raise optuna.TrialPruned()

        return float(np.mean(fold_scores))

    return objective


# ---------------------------------------------------------------------------
# Baseline evaluation (same folds, default params)
# ---------------------------------------------------------------------------


def evaluate_baseline(folds: list[dict[str, Any]], config: MLConfig) -> float:
    """Evaluate baseline LightGBM params on the same precomputed folds."""
    baseline_params = dict(config.lgbm_params)
    baseline_params["verbose"] = -1
    baseline_params["n_jobs"] = -1

    fold_scores = []
    for fold in folds:
        clf = LGBMClassifier(**baseline_params)
        clf.fit(fold["X_train"], fold["y_train"])
        y_pred = clf.predict(fold["X_val"])
        score = float(f1_score(fold["y_val"], y_pred, average="macro", zero_division=0))
        fold_scores.append(score)

    return float(np.mean(fold_scores))


# ---------------------------------------------------------------------------
# 5x5 CV validation
# ---------------------------------------------------------------------------


def validate_5x5(
    X_df: pd.DataFrame,
    labels: np.ndarray,
    config: MLConfig,
    lgbm_params: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    """Run 5x5 repeated stratified k-fold CV with given LightGBM params."""
    rskf = RepeatedStratifiedKFold(n_splits=5, n_repeats=5, random_state=42)
    le = LabelEncoder()
    y_encoded = le.fit_transform(labels)

    fold_scores = []
    n_total = rskf.get_n_splits()

    for fold_idx, (train_idx, val_idx) in enumerate(rskf.split(X_df, y_encoded)):
        X_df_train = X_df.iloc[train_idx]
        X_df_val = X_df.iloc[val_idx]
        y_train = y_encoded[train_idx]
        y_val = y_encoded[val_idx]

        X_train, X_val = prepare_features_for_fold(X_df_train, X_df_val, config)

        params = dict(lgbm_params)
        params["verbose"] = -1
        params["n_jobs"] = -1
        clf = LGBMClassifier(**params)
        clf.fit(X_train, y_train)

        y_pred = clf.predict(X_val)
        score = float(f1_score(y_val, y_pred, average="macro", zero_division=0))
        fold_scores.append(score)

        if (fold_idx + 1) % 5 == 0:
            print(f"  [{label}] {fold_idx + 1}/{n_total} folds, running mean F1 = {np.mean(fold_scores):.4f}")

    scores = np.array(fold_scores)
    return {
        "mean": round(float(scores.mean()), 4),
        "std": round(float(scores.std(ddof=1)), 4),
        "min": round(float(scores.min()), 4),
        "max": round(float(scores.max()), 4),
        "fold_scores": [round(s, 4) for s in fold_scores],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Run Optuna hyperparameter tuning for LightGBM."""
    print("=" * 60)
    print("Optuna LightGBM Hyperparameter Tuning")
    print("=" * 60)

    config = AppConfig()
    config.ensure_dirs()
    db_manager = DatabaseManager(config)

    with db_manager.get_session() as session:
        # Step 1: Load data
        print("\n[1/5] Loading data...")
        txn_inputs, labels = load_data(session)

    # Step 2: Extract raw features and precompute folds
    print("\n[2/5] Extracting features and precomputing folds...")
    X_df = extract_raw_features(txn_inputs, config.ml)
    folds = precompute_folds(X_df, labels, config.ml, n_splits=5)

    # Step 3: Evaluate baseline on the same folds
    print("\n[3/5] Evaluating baseline...")
    baseline_f1 = evaluate_baseline(folds, config.ml)
    print(f"  Baseline macro F1 (1x5): {baseline_f1:.4f}")

    # Step 4: Run Optuna study
    print("\n[4/5] Running Optuna study (100 trials)...")
    start_time = time.time()

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=10),
    )

    objective = create_objective(folds)
    study.optimize(objective, n_trials=100, show_progress_bar=True)

    duration_min = (time.time() - start_time) / 60
    print(f"\n  Study completed in {duration_min:.1f} minutes")
    print(f"  Best trial: #{study.best_trial.number}")
    print(f"  Best macro F1 (1x5): {study.best_value:.4f}")
    print(f"  Improvement over baseline: {(study.best_value - baseline_f1) * 100:+.2f} pp")

    # Step 5: Validate best params with 5x5 CV
    print("\n[5/5] Validating with 5x5 CV...")

    # Build full param dicts for validation
    best_params = dict(study.best_params)
    best_params.update(
        {
            "n_estimators": 1000,
            "class_weight": "balanced",
            "random_state": 42,
        }
    )

    baseline_params = dict(config.ml.lgbm_params)

    print("  Running 5x5 CV for tuned params...")
    tuned_5x5 = validate_5x5(X_df, labels, config.ml, best_params, "tuned")
    print("  Running 5x5 CV for baseline params...")
    baseline_5x5 = validate_5x5(X_df, labels, config.ml, baseline_params, "baseline")

    # Collect top 10 trials
    top_trials = sorted(study.trials, key=lambda t: t.value if t.value is not None else -1, reverse=True)[:10]
    top_10 = [
        {"number": t.number, "value": round(t.value, 4) if t.value else None, "params": t.params} for t in top_trials
    ]

    # Build results
    improvement = study.best_value - baseline_f1
    results = {
        "best_params": best_params,
        "best_macro_f1_1x5": round(study.best_value, 4),
        "baseline_macro_f1_1x5": round(baseline_f1, 4),
        "improvement": f"{improvement * 100:+.2f} pp",
        "n_trials": len(study.trials),
        "n_pruned": len([t for t in study.trials if t.state == optuna.trial.TrialState.PRUNED]),
        "study_duration_minutes": round(duration_min, 1),
        "top_10_trials": top_10,
        "validation_5x5": {
            "tuned": {"macro_f1": tuned_5x5},
            "baseline": {"macro_f1": baseline_5x5},
        },
    }

    # Save results
    output_path = Path("scratch_pads/lgbm_tuning_results.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")

    # Print comparison table
    print("\n" + "=" * 60)
    print("RESULTS COMPARISON")
    print("=" * 60)

    print(f"\n{'Metric':<30} {'Baseline':>12} {'Tuned':>12} {'Delta':>10}")
    print("-" * 64)
    print(f"{'Macro F1 (1x5)':<30} {baseline_f1:>12.4f} {study.best_value:>12.4f} {improvement * 100:>+9.2f}pp")

    improvement_5x5 = tuned_5x5["mean"] - baseline_5x5["mean"]
    print(
        f"{'Macro F1 (5x5 mean)':<30} {baseline_5x5['mean']:>12.4f} {tuned_5x5['mean']:>12.4f}"
        f" {improvement_5x5 * 100:>+9.2f}pp"
    )
    print(f"{'Macro F1 (5x5 std)':<30} {baseline_5x5['std']:>12.4f} {tuned_5x5['std']:>12.4f}")

    print(f"\n{'Parameter':<25} {'Baseline':>15} {'Tuned':>15}")
    print("-" * 55)
    param_keys = [
        "num_leaves",
        "max_depth",
        "learning_rate",
        "feature_fraction",
        "bagging_fraction",
        "bagging_freq",
        "min_child_samples",
        "reg_alpha",
        "reg_lambda",
    ]
    for key in param_keys:
        baseline_val = baseline_params.get(key, "N/A")
        tuned_val = best_params.get(key, "N/A")
        if isinstance(baseline_val, float):
            print(f"{key:<25} {baseline_val:>15.6f} {tuned_val:>15.6f}")
        else:
            print(f"{key:<25} {str(baseline_val):>15} {str(tuned_val):>15}")

    n_estimators_note = "early_stop" if "n_estimators" not in study.best_params else str(best_params["n_estimators"])
    print(f"{'n_estimators':<25} {baseline_params.get('n_estimators', 150):>15} {n_estimators_note:>15}")

    print()


if __name__ == "__main__":
    main()
