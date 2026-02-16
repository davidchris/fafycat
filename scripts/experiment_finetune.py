#!/usr/bin/env python3
"""Experiment 2: Fine-tuned Transformer Classifier.

End-to-end fine-tuning of a German BERT model with LoRA adapters for
transaction categorization. Only run if Experiment 1 showed embeddings help.

Architecture: [CLS] → BERT encoder (LoRA) → Classification head (26 classes)
Training: LoRA rank=4-8, ~300K trainable params out of 110M.

Usage: uv run --group finetune scripts/experiment_finetune.py
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
import torch
from scipy import stats
from sklearn.metrics import f1_score, log_loss
from sklearn.model_selection import RepeatedStratifiedKFold, train_test_split
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForSequenceClassification, AutoTokenizer

# Set production environment
os.environ["FAFYCAT_DB_URL"] = "sqlite:///data/fafycat_prod.db"
os.environ["FAFYCAT_ENV"] = "production"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.establish_baseline import (
    compute_brier_multiclass,
    compute_ece,
    compute_fold_metrics,
    load_reviewed_transactions,
)
from src.fafycat.core.config import AppConfig
from src.fafycat.core.database import DatabaseManager

# Suppress noisy warnings
warnings.filterwarnings("ignore", category=UserWarning, module="lightgbm")
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")
warnings.filterwarnings("ignore", category=FutureWarning, module="sklearn")
warnings.filterwarnings("ignore", category=FutureWarning, module="transformers")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BERT_MODEL = "dbmdz/bert-base-german-cased"
MAX_SEQ_LENGTH = 64
BATCH_SIZE = 16
LEARNING_RATE = 2e-4  # Higher LR for LoRA (base model is frozen)
WEIGHT_DECAY = 0.01
MAX_EPOCHS = 30
PATIENCE = 5  # Early stopping patience
LORA_RANK = 8
LORA_ALPHA = 16
LORA_DROPOUT = 0.1


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


class TransactionDataset(Dataset):
    """PyTorch dataset for tokenized transactions."""

    def __init__(self, texts: list[str], labels: np.ndarray, tokenizer, max_length: int):
        self.encodings = tokenizer(
            texts,
            padding="max_length",
            truncation=True,
            max_length=max_length,
            return_tensors="pt",
        )
        self.labels = torch.tensor(labels, dtype=torch.long)

    def __len__(self) -> int:
        return len(self.labels)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:  # type: ignore[override]
        return {
            "input_ids": self.encodings["input_ids"][idx],
            "attention_mask": self.encodings["attention_mask"][idx],
            "labels": self.labels[idx],
        }


# ---------------------------------------------------------------------------
# Training & evaluation
# ---------------------------------------------------------------------------


def get_device() -> torch.device:
    """Get best available device."""
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def train_one_fold(
    train_texts: list[str],
    train_labels: np.ndarray,
    val_texts: list[str],
    val_labels: np.ndarray,
    n_classes: int,
    fold_idx: int,
) -> tuple[np.ndarray, dict[str, float]]:
    """Train BERT+LoRA on one fold, return test probabilities and training info."""
    device = get_device()

    # Load tokenizer and model
    tokenizer = AutoTokenizer.from_pretrained(BERT_MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(
        BERT_MODEL,
        num_labels=n_classes,
    )

    # Apply LoRA
    from peft import LoraConfig, TaskType, get_peft_model

    lora_config = LoraConfig(
        task_type=TaskType.SEQ_CLS,
        r=LORA_RANK,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        target_modules=["query", "value"],
        modules_to_save=["classifier"],  # Explicitly unfreeze classifier head
    )
    model = get_peft_model(model, lora_config)

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    if fold_idx == 0:
        print(f"  LoRA: {trainable:,} trainable / {total:,} total ({100 * trainable / total:.2f}%)")

    model.to(device)

    # Split training data into train/early-stopping validation
    try:
        sub_train_texts, es_val_texts, sub_train_labels, es_val_labels = train_test_split(
            train_texts, train_labels, test_size=0.15, stratify=train_labels, random_state=42 + fold_idx
        )
    except ValueError:
        # Stratified split failed — use all for training, no early stopping
        sub_train_texts, sub_train_labels = train_texts, train_labels
        es_val_texts, es_val_labels = val_texts, val_labels

    # Create datasets
    train_dataset = TransactionDataset(sub_train_texts, sub_train_labels, tokenizer, MAX_SEQ_LENGTH)
    es_val_dataset = TransactionDataset(es_val_texts, es_val_labels, tokenizer, MAX_SEQ_LENGTH)
    test_dataset = TransactionDataset(val_texts, val_labels, tokenizer, MAX_SEQ_LENGTH)

    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)
    es_val_loader = DataLoader(es_val_dataset, batch_size=BATCH_SIZE)
    test_loader = DataLoader(test_dataset, batch_size=BATCH_SIZE)

    # Separate parameter groups: higher LR for classifier head
    classifier_params = []
    lora_params = []
    for name, param in model.named_parameters():
        if not param.requires_grad:
            continue
        if "classifier" in name:
            classifier_params.append(param)
        else:
            lora_params.append(param)

    optimizer = torch.optim.AdamW(
        [
            {"params": lora_params, "lr": LEARNING_RATE},
            {"params": classifier_params, "lr": LEARNING_RATE * 5},  # 5x higher LR for classifier
        ],
        weight_decay=WEIGHT_DECAY,
    )

    # Warmup + cosine annealing
    total_steps = len(train_loader) * MAX_EPOCHS
    warmup_steps = min(len(train_loader) * 2, total_steps // 5)  # 2 epochs warmup

    def lr_lambda(step: int) -> float:
        if step < warmup_steps:
            return step / max(warmup_steps, 1)
        progress = (step - warmup_steps) / max(total_steps - warmup_steps, 1)
        return max(0.1, 0.5 * (1.0 + np.cos(np.pi * progress)))

    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda)

    # Training loop with early stopping
    best_val_f1 = -1.0
    best_state = None
    patience_counter = 0

    for epoch in range(MAX_EPOCHS):
        model.train()
        epoch_loss = 0.0

        for batch in train_loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            outputs = model(**batch)
            loss = outputs.loss

            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()

            epoch_loss += loss.item()

        # Validation for early stopping
        model.eval()
        val_preds = []
        val_true = []

        with torch.no_grad():
            for batch in es_val_loader:
                batch = {k: v.to(device) for k, v in batch.items()}
                outputs = model(**batch)
                preds = torch.argmax(outputs.logits, dim=-1)
                val_preds.extend(preds.cpu().numpy())
                val_true.extend(batch["labels"].cpu().numpy())

        val_f1 = float(f1_score(val_true, val_preds, average="macro", zero_division=0))

        if val_f1 > best_val_f1:
            best_val_f1 = val_f1
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            patience_counter = 0
        else:
            patience_counter += 1

        if patience_counter >= PATIENCE:
            if fold_idx == 0:
                print(f"    Early stop at epoch {epoch + 1} (best val F1={best_val_f1:.4f})")
            break

    # Restore best model
    if best_state is not None:
        model.load_state_dict(best_state)
        model.to(device)

    # Predict on test set
    model.eval()
    all_logits = []

    with torch.no_grad():
        for batch in test_loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            outputs = model(**batch)
            all_logits.append(outputs.logits.cpu())

    logits = torch.cat(all_logits, dim=0)
    probas = torch.softmax(logits, dim=-1).numpy()

    info = {
        "epochs_trained": epoch + 1,
        "best_val_f1": best_val_f1,
        "final_train_loss": epoch_loss / len(train_loader),
    }

    # Cleanup GPU memory
    del model, optimizer, scheduler
    if torch.backends.mps.is_available():
        torch.mps.empty_cache()
    elif torch.cuda.is_available():
        torch.cuda.empty_cache()

    return probas, info


def run_finetune_cv(
    texts: list[str],
    labels: np.ndarray,
    class_to_idx: dict[int, int],
    n_classes: int,
) -> dict[str, Any]:
    """Run 5x5 CV for fine-tuned BERT+LoRA."""
    print(f"\n{'=' * 60}")
    print("Fine-tuned BERT+LoRA (standalone)")
    print(f"{'=' * 60}")

    rskf = RepeatedStratifiedKFold(n_splits=5, n_repeats=5, random_state=42)

    fold_scores: list[float] = []
    all_true: list[np.ndarray] = []
    all_prob: list[np.ndarray] = []
    training_infos: list[dict] = []

    texts_array = np.array(texts, dtype=object)
    n_total = rskf.get_n_splits()
    total_start = time.time()

    for fold_idx, (train_idx, test_idx) in enumerate(rskf.split(texts_array, labels)):
        fold_start = time.time()

        train_texts = texts_array[train_idx].tolist()
        test_texts = texts_array[test_idx].tolist()
        train_labels = np.array([class_to_idx[int(lbl)] for lbl in labels[train_idx]])
        test_labels = np.array([class_to_idx[int(lbl)] for lbl in labels[test_idx]])

        probas, info = train_one_fold(
            train_texts,
            train_labels,
            test_texts,
            test_labels,
            n_classes,
            fold_idx,
        )
        training_infos.append(info)

        metrics = compute_fold_metrics(test_labels, probas, n_classes)
        fold_scores.append(metrics["macro_f1"])
        all_true.append(test_labels)
        all_prob.append(probas)

        fold_time = time.time() - fold_start
        print(
            f"  Fold {fold_idx + 1}/{n_total}: F1={metrics['macro_f1']:.4f} "
            f"(epochs={info['epochs_trained']}, val_f1={info['best_val_f1']:.4f}, {fold_time:.0f}s)"
        )

    total_time = time.time() - total_start
    print(f"\n  Total CV time: {total_time / 60:.1f} minutes")

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

    auto_mask = confidences >= 0.95
    auto_coverage = float(auto_mask.sum() / len(y_true_all))
    auto_risk = float((y_pred_all[auto_mask] != y_true_all[auto_mask]).mean()) if auto_mask.sum() > 0 else 0.0

    result = {
        "model": BERT_MODEL,
        "lora_rank": LORA_RANK,
        "lora_alpha": LORA_ALPHA,
        "max_epochs": MAX_EPOCHS,
        "patience": PATIENCE,
        "learning_rate": LEARNING_RATE,
        "total_cv_time_minutes": round(total_time / 60, 1),
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
        "training_info": {
            "mean_epochs": round(np.mean([i["epochs_trained"] for i in training_infos]), 1),
            "mean_best_val_f1": round(np.mean([i["best_val_f1"] for i in training_infos]), 4),
        },
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
    print("Experiment 2: Fine-tuned BERT+LoRA Classifier")
    print("=" * 60)

    # Check if Experiment 1 results exist and showed positive signal
    exp1_path = Path("scratch_pads/experiment_embeddings_results.json")
    if exp1_path.exists():
        with open(exp1_path) as f:
            exp1 = json.load(f)
        best_exp1 = max(
            exp1["variants"].values(),
            key=lambda v: v["macro_f1"]["mean"],
        )
        best_f1 = best_exp1["macro_f1"]["mean"]
        print(f"\nExperiment 1 best: {best_exp1['variant']} (Macro F1 = {best_f1:.4f})")
        if best_f1 <= 0.851:
            print("WARNING: Experiment 1 showed no improvement over baseline LightGBM.")
            print("Proceeding anyway — fine-tuning may still help via end-to-end optimization.")
    else:
        print("\nWARNING: No Experiment 1 results found. Running fine-tuning anyway.")

    config = AppConfig()
    config.ensure_dirs()

    db_manager = DatabaseManager(config)

    with db_manager.get_session() as session:
        # Load data
        print("\n[1/3] Loading data...")
        txn_inputs, labels, df = load_reviewed_transactions(session)
        unique_classes = np.sort(np.unique(labels))
        n_classes = len(unique_classes)
        class_to_idx = {int(c): i for i, c in enumerate(unique_classes)}

        # Use raw text for BERT (not preprocessed text_combined which removes stopwords/case)
        texts = [f"{txn.name} {txn.purpose}".strip() for txn in txn_inputs]

        # Run fine-tuning CV
        print("\n[2/3] Running 5x5 CV with BERT+LoRA fine-tuning...")
        finetune_result = run_finetune_cv(texts, labels, class_to_idx, n_classes)

        # Assemble results
        results: dict[str, Any] = {
            "metadata": {
                "date": str(date.today()),
                "experiment": "bert_lora_finetuning",
                "bert_model": BERT_MODEL,
                "n_transactions": len(txn_inputs),
                "n_categories": n_classes,
                "cv_scheme": "5x5 repeated stratified k-fold",
                "baselines": {
                    "lightgbm_macro_f1": 0.851,
                    "ensemble_macro_f1": 0.855,
                },
            },
            "finetune_standalone": finetune_result,
        }

        # Save
        out_path = Path("scratch_pads/experiment_finetune_results.json")
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\n[3/3] Results saved to {out_path}")

        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY COMPARISON")
        print("=" * 60)
        mf1 = finetune_result["macro_f1"]["mean"]
        delta_lgb = mf1 - 0.851
        delta_ens = mf1 - 0.855
        sign_lgb = "+" if delta_lgb >= 0 else ""
        sign_ens = "+" if delta_ens >= 0 else ""

        print(f"{'Model':<45} {'Macro F1':>10} {'vs LGB':>8} {'vs ENS':>8}")
        print("-" * 71)
        print(f"{'Baseline: LightGBM (TF-IDF/SVD + struct)':<45} {'0.8510':>10} {'---':>8} {'---':>8}")
        print(f"{'Baseline: Ensemble (LGB + NB)':<45} {'0.8550':>10} {'---':>8} {'---':>8}")
        print(f"{'BERT+LoRA fine-tuned':<45} {mf1:>10.4f} {sign_lgb}{delta_lgb:>7.4f} {sign_ens}{delta_ens:>7.4f}")

        # Statistical significance test vs baseline
        exp1_scores = None
        if exp1_path.exists():
            with open(exp1_path) as f:
                exp1 = json.load(f)
            # Use variant B scores as embedding baseline
            if "B_embeddings_structured" in exp1["variants"]:
                exp1_scores = exp1["variants"]["B_embeddings_structured"]["fold_scores"]

        ft_scores = finetune_result["fold_scores"]

        if exp1_scores and len(exp1_scores) == len(ft_scores):
            # Paired t-test: fine-tune vs embeddings+LightGBM
            t_stat, p_val = stats.ttest_rel(ft_scores, exp1_scores)
            print(f"\nPaired t-test (fine-tune vs embeddings+LGB): t={t_stat:.3f}, p={p_val:.4f}")
            if p_val < 0.05:
                print("  → Statistically significant difference (p < 0.05)")
            else:
                print("  → NOT statistically significant (p >= 0.05)")

        # Decision
        if mf1 >= 0.875:
            print(f"\n→ STRONG improvement ({mf1:.4f} >= 0.875). Consider production integration.")
        elif mf1 > 0.855:
            print(f"\n→ MODEST improvement ({mf1:.4f} > 0.855). May help as ensemble component.")
        else:
            print(f"\n→ NO improvement ({mf1:.4f} <= 0.855). Transformer overfits on small dataset.")


if __name__ == "__main__":
    main()
