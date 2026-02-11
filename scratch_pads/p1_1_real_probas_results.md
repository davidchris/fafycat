# P1-1: Pass Full LightGBM Probabilities to Ensemble — Results

**Date:** 2026-02-11
**Branch:** `feat/improve-auto-predictions`
**Baseline reference:** `scratch_pads/baseline_metrics.json` (pre-change Macro F1 summary: LGB 0.856, NB 0.793, ENS 0.861)

## What Changed

Replaced the fake probability reconstruction in `EnsembleCategorizer` (argmax + uniform residual) with full calibrated LightGBM probability vectors via a new `predict_proba()` method. Added proper class-alignment helpers. Removed ~100 lines of dead code (`LightGBMWrapper`, `_convert_lgbm_to_probas`, `_convert_lgbm_predictions_to_probas`, `_calculate_cv_metrics`).

## Results (5x5 Repeated Stratified K-Fold, 1856 transactions, 26 categories)

| Metric | LightGBM | Naive Bayes | Ensemble | ENS vs LGB |
|--------|----------|-------------|----------|------------|
| **Macro F1** | 0.856 | 0.793 | **0.861** | +0.5% |
| **Weighted F1** | 0.884 | 0.821 | **0.887** | +0.3% |
| **Log Loss** | 0.697 | 0.923 | **0.631** | **-9.4%** |
| **Brier Score** | 0.0079 | 0.0115 | 0.0080 | +0.1% |
| **ECE (8 bins)** | 0.081 | 0.180 | 0.131 | +6.1% |
| **Auto-approve coverage** (>=0.95) | 94.3% | 34.1% | 39.1% | — |
| **Auto-approve error rate** (>=0.95) | 7.9% | 1.3% | **0.69%** | — |

### Macro F1 with Confidence Interval

```
Ensemble: 0.861 +/- 0.023  95% CI [0.836, 0.886]
LightGBM: 0.856 +/- 0.022  95% CI [0.831, 0.880]
```

CIs overlap heavily — Macro F1 improvement is not statistically significant.

## Key Observations

### 1. Macro F1 unchanged (as expected)
The ensemble Macro F1 (0.861) is identical to the previous baseline. The baseline evaluation script already used correct full probabilities (`get_lgbm_probas()`), so the CV results are measuring the same underlying model quality. The change improves the **production code path**, not the evaluation.

### 2. Log Loss improved significantly (-9.4% vs LightGBM solo)
The ensemble's log loss (0.631) is substantially better than LightGBM solo (0.697). This is the clearest win: the combined probability distributions are more informative than either model alone. Log loss is a proper scoring rule that evaluates the **full probability vector**, not just the argmax — exactly where this change has impact.

### 3. Weight shift: LightGBM 0.4 / NB 0.6 (production training)
Production training (`train_model.py`) now picks LightGBM=0.4, NB=0.6 — a reversal from the previous default of 0.7/0.3. This is correct: with real probabilities flowing through, the optimizer no longer needs to overweight LightGBM just to get its hard prediction to dominate. NB's soft per-class discrimination becomes genuinely useful.

### 4. Auto-approve: very low error rate but low coverage
The ensemble at the 0.95 threshold covers 39.1% of transactions with only 0.69% error rate. Compare to LightGBM solo: 94.3% coverage but 7.9% error rate. The ensemble is far more conservative but much more reliable. This is likely because properly-combined probabilities rarely yield extreme confidence.

### 5. ECE (calibration) is a concern
Ensemble ECE (0.131) is worse than LightGBM solo (0.081). The probability combination shifts the distribution — the ensemble is less calibrated even though its predictions are better. This suggests that post-hoc calibration of the ensemble output (e.g., temperature scaling) could be a worthwhile follow-up.

### Risk-Coverage Curve (Ensemble)

| Threshold | Coverage | Error Rate |
|-----------|----------|------------|
| 0.50 | 75.5% | 2.8% |
| 0.60 | 69.1% | 1.5% |
| 0.70 | 63.7% | 1.1% |
| 0.80 | 58.7% | 0.8% |
| 0.90 | 50.8% | 0.7% |
| 0.95 | 39.1% | 0.7% |
| 0.99 | 11.3% | 1.2% |

## Summary

This change is a **correctness fix**, not primarily a performance optimization. The ensemble now uses real probability vectors instead of fake reconstructions. Macro F1 is unchanged (expected, since the evaluation already used correct probabilities). The main wins are:

- **Log loss -9.4%** (better probability quality)
- **Auto-approve error rate 0.69%** (very reliable when confident)
- **Code quality**: removed ~100 lines of dead code, eliminated the information-destroying fake proba reconstruction
- **Weight optimization now works correctly** — finds the true optimal blend rather than compensating for broken inputs

### Potential Follow-ups

- **ECE improvement**: Apply temperature scaling or Platt scaling to ensemble output
- **Auto-approve threshold tuning**: Current 0.95 gives only 39% coverage; could lower to 0.80 for 59% coverage at 0.8% error
- **Batch prediction**: `predict_proba()` already works in batch; update `predict_with_confidence()` to process all transactions at once instead of one-by-one
