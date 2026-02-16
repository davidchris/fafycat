#!/usr/bin/env python3
"""Experiment 1: Sentence Transformer Embeddings + LightGBM.

Tests whether frozen transformer embeddings capture more signal than TF-IDF
char/word n-grams for German banking transaction categorization.

Usage: uv run --group experiments scripts/experiment_embeddings.py

Variants:
  A: Embeddings (384d) only → LightGBM
  B: Embeddings (384d) + structured features (27d) → LightGBM
  C: Embeddings (384d) + TF-IDF/SVD (100d) + structured features → LightGBM

Baseline comparison: LGB solo = 0.851, Ensemble = 0.855 (5x5 CV Macro F1).
"""

import json
import os
import sys
import time
import warnings
from datetime import date
from math import sqrt
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from scipy import stats
from sentence_transformers import SentenceTransformer
from sklearn.metrics import f1_score, log_loss
from sklearn.model_selection import RepeatedStratifiedKFold

# Set production environment
os.environ["FAFYCAT_DB_URL"] = "sqlite:///data/fafycat_prod.db"
os.environ["FAFYCAT_ENV"] = "production"

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.establish_baseline import (
    compute_brier_multiclass,
    compute_ece,
    compute_fold_metrics,
    load_reviewed_transactions,
)
from src.fafycat.core.config import AppConfig, MLConfig
from src.fafycat.core.database import DatabaseManager
from src.fafycat.ml.feature_extractor import FeatureExtractor

# Suppress noisy warnings during CV
warnings.filterwarnings("ignore", category=UserWarning, module="lightgbm")
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")
warnings.filterwarnings("ignore", category=FutureWarning, module="sklearn")

# ---------------------------------------------------------------------------
# Embedding computation
# ---------------------------------------------------------------------------

EMBEDDING_MODELS = [
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
]


def compute_embeddings(texts: list[str], model_name: str) -> np.ndarray:
    """Compute sentence embeddings for all texts at once (frozen model)."""
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"  Loading {model_name} on {device}...")
    model = SentenceTransformer(model_name, device=device)

    t0 = time.time()
    embeddings = model.encode(
        texts,
        batch_size=64,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    elapsed = time.time() - t0
    print(f"  Encoded {len(texts)} texts → {embeddings.shape} in {elapsed:.1f}s")
    return embeddings


# ---------------------------------------------------------------------------
# CV evaluation
# ---------------------------------------------------------------------------


def run_embedding_cv(
    embeddings: np.ndarray,
    structured_features: np.ndarray | None,
    tfidf_svd_features: np.ndarray | None,
    labels: np.ndarray,
    config: MLConfig,
    variant_name: str,
) -> dict[str, Any]:
    """Run 5x5 CV for one embedding variant."""
    print(f"\n{'=' * 60}")
    print(f"Variant {variant_name}")
    print(f"{'=' * 60}")

    # Build feature matrix
    components = [embeddings]
    desc_parts = [f"emb({embeddings.shape[1]})"]

    if structured_features is not None:
        components.append(structured_features)
        desc_parts.append(f"struct({structured_features.shape[1]})")

    if tfidf_svd_features is not None:
        components.append(tfidf_svd_features)
        desc_parts.append(f"tfidf_svd({tfidf_svd_features.shape[1]})")

    X = np.hstack(components)
    print(f"Feature matrix: {X.shape} = {' + '.join(desc_parts)}")

    rskf = RepeatedStratifiedKFold(n_splits=5, n_repeats=5, random_state=42)
    unique_classes = np.sort(np.unique(labels))
    n_classes = len(unique_classes)
    class_to_idx = {int(c): i for i, c in enumerate(unique_classes)}

    fold_scores: list[float] = []
    all_true: list[np.ndarray] = []
    all_prob: list[np.ndarray] = []

    from lightgbm import LGBMClassifier

    n_total = rskf.get_n_splits()
    for fold_idx, (train_idx, test_idx) in enumerate(rskf.split(X, labels)):
        X_train, X_test = X[train_idx], X[test_idx]
        y_train = np.array([class_to_idx[int(lbl)] for lbl in labels[train_idx]])
        y_test = np.array([class_to_idx[int(lbl)] for lbl in labels[test_idx]])

        clf = LGBMClassifier(**config.lgbm_params)
        clf.fit(X_train, y_train)
        probas = clf.predict_proba(X_test)

        metrics = compute_fold_metrics(y_test, probas, n_classes)
        fold_scores.append(metrics["macro_f1"])
        all_true.append(y_test)
        all_prob.append(probas)

        if (fold_idx + 1) % 5 == 0:
            recent = fold_scores[-5:]
            print(f"  Folds {fold_idx - 3}-{fold_idx + 1}/{n_total}: mean F1={np.mean(recent):.4f}")

    # Aggregate
    y_true_all = np.concatenate(all_true)
    y_prob_all = np.concatenate(all_prob)
    y_pred_all = np.argmax(y_prob_all, axis=1)
    confidences = np.max(y_prob_all, axis=1)

    scores = np.array(fold_scores)
    mean_score = float(scores.mean())
    std_score = float(scores.std(ddof=1))
    n_folds = len(fold_scores)
    corrected_se = std_score * sqrt(1 / n_folds + 0.2 / 0.8)
    t_crit = float(stats.t.ppf(0.975, df=n_folds - 1))
    ci_low = mean_score - t_crit * corrected_se
    ci_high = mean_score + t_crit * corrected_se

    # Auto-approve stats
    auto_mask = confidences >= 0.95
    auto_coverage = float(auto_mask.sum() / len(y_true_all))
    auto_risk = float((y_pred_all[auto_mask] != y_true_all[auto_mask]).mean()) if auto_mask.sum() > 0 else 0.0

    result = {
        "variant": variant_name,
        "feature_dim": X.shape[1],
        "macro_f1": {
            "mean": round(mean_score, 4),
            "std": round(std_score, 4),
            "ci_95": [round(ci_low, 4), round(ci_high, 4)],
        },
        "macro_f1_aggregate": round(float(f1_score(y_true_all, y_pred_all, average="macro", zero_division=0)), 4),
        "weighted_f1": round(float(f1_score(y_true_all, y_pred_all, average="weighted", zero_division=0)), 4),
        "log_loss": round(float(log_loss(y_true_all, y_prob_all, labels=list(range(n_classes)))), 4),
        "brier_score": round(compute_brier_multiclass(y_true_all, y_prob_all), 4),
        "ece_8bins": round(compute_ece(y_true_all, y_prob_all, n_bins=8), 4),
        "auto_approve_0.95": {
            "coverage": round(auto_coverage, 4),
            "selective_risk": round(auto_risk, 4),
        },
        "fold_scores": [round(s, 4) for s in fold_scores],
    }

    mf1 = result["macro_f1"]
    aa = result["auto_approve_0.95"]
    ci = mf1["ci_95"]
    print(f"\n  Macro F1:     {mf1['mean']:.4f} +/- {mf1['std']:.4f}  95% CI [{ci[0]:.4f}, {ci[1]:.4f}]")
    print(f"  Weighted F1:  {result['weighted_f1']:.4f}")
    print(f"  Log Loss:     {result['log_loss']:.4f}")
    print(f"  Brier Score:  {result['brier_score']:.4f}")
    print(f"  ECE (8 bins): {result['ece_8bins']:.4f}")
    print(f"  Auto-approve: {aa['coverage'] * 100:.1f}% coverage, {aa['selective_risk'] * 100:.1f}% error rate")

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("=" * 60)
    print("Experiment 1: Sentence Transformer Embeddings + LightGBM")
    print("=" * 60)

    config = AppConfig()
    config.ensure_dirs()
    config.ml.lgbm_params["verbose"] = -1
    config.ml.lgbm_params["n_jobs"] = 8

    db_manager = DatabaseManager(config)

    with db_manager.get_session() as session:
        # Load data
        print("\n[1/4] Loading data...")
        txn_inputs, labels, df = load_reviewed_transactions(session)
        n_samples = len(txn_inputs)
        unique_classes = np.sort(np.unique(labels))

        # Extract text for embeddings
        feature_extractor = FeatureExtractor()
        features_list = feature_extractor.extract_batch_features(txn_inputs)
        features_df = pd.DataFrame(features_list)
        texts = features_df["text_combined"].fillna("").tolist()

        # Extract structured features (same ones LightGBM uses)
        numerical_features = feature_extractor.get_numerical_feature_names()
        structured = features_df[numerical_features].fillna(0).values
        print(f"  Structured features: {structured.shape}")

        # Compute TF-IDF/SVD features (same pipeline as baseline LightGBM)
        print("\n[2/4] Computing TF-IDF/SVD features (baseline pipeline)...")
        from scipy.sparse import hstack as sparse_hstack
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer

        char_vec = TfidfVectorizer(**config.ml.tfidf_char_params)
        word_vec = TfidfVectorizer(**config.ml.tfidf_word_params)
        svd = TruncatedSVD(n_components=config.ml.svd_n_components, random_state=42)

        text_array = features_df["text_combined"].fillna("").values
        X_char = char_vec.fit_transform(text_array)
        X_word = word_vec.fit_transform(text_array)
        X_sparse = sparse_hstack([X_char, X_word])
        tfidf_svd = svd.fit_transform(X_sparse)
        print(f"  TF-IDF/SVD features: {tfidf_svd.shape}")

        # Compute embeddings
        print("\n[3/4] Computing sentence embeddings...")
        model_name = EMBEDDING_MODELS[0]
        embeddings = compute_embeddings(texts, model_name)

        # Run variants
        print("\n[4/4] Running 5x5 CV for each variant...")
        results: dict[str, Any] = {
            "metadata": {
                "date": str(date.today()),
                "experiment": "sentence_transformer_embeddings",
                "embedding_model": model_name,
                "embedding_dim": embeddings.shape[1],
                "n_transactions": n_samples,
                "n_categories": len(unique_classes),
                "cv_scheme": "5x5 repeated stratified k-fold",
                "baselines": {
                    "lightgbm_macro_f1": 0.851,
                    "ensemble_macro_f1": 0.855,
                },
            },
            "variants": {},
        }

        # Variant A: Embeddings only
        results["variants"]["A_embeddings_only"] = run_embedding_cv(
            embeddings=embeddings,
            structured_features=None,
            tfidf_svd_features=None,
            labels=labels,
            config=config.ml,
            variant_name="A: Embeddings only (384d)",
        )

        # Variant B: Embeddings + structured features
        results["variants"]["B_embeddings_structured"] = run_embedding_cv(
            embeddings=embeddings,
            structured_features=structured,
            tfidf_svd_features=None,
            labels=labels,
            config=config.ml,
            variant_name="B: Embeddings (384d) + Structured (27d)",
        )

        # Variant C: Embeddings + TF-IDF/SVD + structured features
        results["variants"]["C_embeddings_tfidf_structured"] = run_embedding_cv(
            embeddings=embeddings,
            structured_features=structured,
            tfidf_svd_features=tfidf_svd,
            labels=labels,
            config=config.ml,
            variant_name="C: Embeddings (384d) + TF-IDF/SVD (100d) + Structured (27d)",
        )

        # Save results
        out_path = Path("scratch_pads/experiment_embeddings_results.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to {out_path}")

        # Summary comparison
        print("\n" + "=" * 60)
        print("SUMMARY COMPARISON")
        print("=" * 60)
        print(f"{'Variant':<50} {'Macro F1':>10} {'vs LGB':>8} {'vs ENS':>8}")
        print("-" * 76)
        print(f"{'Baseline: LightGBM (TF-IDF/SVD + struct)':<50} {'0.8510':>10} {'---':>8} {'---':>8}")
        print(f"{'Baseline: Ensemble (LGB + NB)':<50} {'0.8550':>10} {'---':>8} {'---':>8}")

        for _variant_key, variant_result in results["variants"].items():
            name = variant_result["variant"]
            mf1 = variant_result["macro_f1"]["mean"]
            delta_lgb = mf1 - 0.851
            delta_ens = mf1 - 0.855
            sign_lgb = "+" if delta_lgb >= 0 else ""
            sign_ens = "+" if delta_ens >= 0 else ""
            print(f"{name:<50} {mf1:>10.4f} {sign_lgb}{delta_lgb:>7.4f} {sign_ens}{delta_ens:>7.4f}")

        # Decision
        best_variant = max(results["variants"].values(), key=lambda v: v["macro_f1"]["mean"])
        best_f1 = best_variant["macro_f1"]["mean"]
        print(f"\nBest variant: {best_variant['variant']} (Macro F1 = {best_f1:.4f})")

        if best_f1 > 0.87:
            print("→ STRONG signal. Proceed to Experiment 2 (fine-tuning).")
        elif best_f1 > 0.855:
            print("→ MODEST improvement. Consider as ensemble component.")
        else:
            print("→ NO improvement. Embeddings don't help for this text type.")


if __name__ == "__main__":
    main()
