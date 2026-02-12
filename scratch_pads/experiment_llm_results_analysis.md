# Experiment 3: Local LLM Classification — Results & Decision

**Date:** 2026-02-12
**Decision: SKIP — Local LLMs do not improve over the ML ensemble for transaction categorization.**

## Experiment Setup

- **Dataset:** 1,856 human-reviewed transactions across 26 categories
- **Evaluation:** 1x5 stratified k-fold cross-validation (screening)
- **Modes tested:** LLM standalone, ensemble standalone, hybrid (ensemble when confident, LLM otherwise)
- **Models:**
  - Phi-4-mini-instruct-4bit (3.8B dense)
  - Qwen3-8B-4bit (8B dense, multilingual)
- **Prompt:** German system prompt with category descriptions + 52 few-shot examples (2 per category), greedy decoding
- **Infrastructure:** Apple Silicon, mlx-lm with KV cache prefilling (~3,000-4,600 shared prefix tokens cached per fold)

## Results

### Model Comparison (1x5 CV, Macro F1)

| Mode | Phi-4-mini | Qwen3-8B | Ensemble |
|------|-----------|----------|----------|
| LLM standalone | 0.503 | **0.674** | — |
| Ensemble standalone | 0.867 | 0.867 | **0.867** |
| Hybrid (t=0.95) | 0.670 | 0.734 | — |
| Best hybrid (swept) | 0.789 (t=0.50) | 0.831 (t=0.50) | — |
| Parse rate | 99.0% | 100.0% | — |

### Hybrid Threshold Sweep (Qwen3-8B, best model)

The hybrid uses the ensemble prediction when its confidence exceeds the threshold, and the LLM prediction otherwise.

| Threshold | Hybrid F1 | % sent to LLM |
|-----------|----------|---------------|
| 0.50 | 0.831 | ~40% |
| 0.60 | 0.804 | ~50% |
| 0.70 | 0.792 | ~55% |
| 0.80 | 0.780 | ~60% |
| 0.90 | 0.756 | ~65% |
| 0.95 | 0.734 | ~55% |

Even at the best threshold (0.50), the hybrid (0.831) is **still 3.6 points below the ensemble alone (0.867)**.

### Per-Category Analysis (Qwen3-8B vs Ensemble)

Categories where the LLM is notably worse than the ensemble:

| Category | Ensemble F1 | LLM F1 | Gap |
|----------|------------|--------|-----|
| kind | 0.823 | 0.241 | -0.58 |
| haushalt | 0.884 | 0.419 | -0.47 |
| sonstiges | 0.889 | 0.098 | -0.79 |
| bargeld | 0.984 | 0.480 | -0.50 |
| flora61 | 0.917 | 0.385 | -0.53 |
| lebensmittel | 0.937 | 0.711 | -0.23 |

Categories where the LLM does comparably well:

| Category | Ensemble F1 | LLM F1 |
|----------|------------|--------|
| dsl | 1.000 | 1.000 |
| investieren | 1.000 | 1.000 |
| kindergeld | 1.000 | 1.000 |
| strom | 1.000 | 1.000 |
| taschengeld | 0.983 | 1.000 |
| einkommen-p2 | 0.960 | 0.974 |

The LLM matches the ensemble only on categories that are already easy (distinctive names, clear patterns). On ambiguous or context-dependent categories, the ensemble is far superior.

## Why the LLM Fails Here

1. **The ensemble already exploits the signal well.** Transaction categorization is primarily a text classification task over short, structured text (name + purpose). The LightGBM + Naive Bayes ensemble with engineered features captures the relevant patterns effectively — there's little headroom for a generative model to add value.

2. **LLMs lack domain-specific training signal.** The ensemble is trained directly on the user's labeled data and learns personal category boundaries (e.g., "flora61" is a specific vendor). The LLM can only rely on general knowledge and the 52 few-shot examples, which is insufficient for idiosyncratic personal categories.

3. **Ambiguous categories confuse the LLM.** Categories like "sonstiges" (miscellaneous), "haushalt" (household), and "kind" (children) have overlapping descriptions. The ensemble learns the decision boundaries from hundreds of labeled examples; the LLM with 2 examples per category cannot.

4. **Scale mismatch.** With only ~50-100 tokens of transaction-specific input, the discriminative signal is thin. A trained classifier with feature engineering (TF-IDF, amount buckets, merchant patterns) extracts more from this limited signal than a generalist LLM prompted in zero/few-shot mode.

5. **The hybrid hurts rather than helps.** The LLM is called for transactions where the ensemble is uncertain — precisely the hard cases. The LLM performs even worse on these ambiguous transactions, dragging down the hybrid below the ensemble alone.

## Technical Notes

- **Qwen3 thinking mode:** Qwen3 models default to chain-of-thought "thinking mode" which generates verbose reasoning before answering. This caused 96% parse failures and 0.1 txn/s throughput until disabled via `enable_thinking=False` in the chat template.
- **KV cache prefilling:** Shared prompt prefix (~3,000-4,600 tokens) is prefilled once per fold and deep-copied per transaction. This gave ~6.5x speedup (0.4 -> 2.6 txn/s), making the full experiment feasible in ~25 minutes instead of ~3 hours.
- **5x5 CV not triggered:** The hybrid F1 (0.734 at t=0.95) was well below the 0.860 threshold, so the more rigorous 5x5 CV phase was skipped.

## Would Larger/Better LLMs Change the Outcome?

The 19-point gap between the best LLM (Qwen3-8B, 0.674) and the ensemble (0.867) is large. It's worth considering whether frontier models — cloud-hosted or future local models — could close it.

### Scaling from 3.8B to 8B

Phi-4-mini (3.8B) scored 0.503, Qwen3-8B scored 0.674 — a +17 point gain from roughly doubling parameters. This is a meaningful jump, and suggests that model capability does matter for this task. However, gains from scaling are typically sublinear: the jump from 8B to 70B is unlikely to yield another +17 points.

### What a frontier model might achieve

Cloud-hosted models (Claude, GPT-4, Gemini) would likely improve in several areas:

- **Better German language understanding.** The 4-bit quantized local models are trained primarily on English. Frontier models have stronger multilingual capabilities, which matters for German transaction descriptions with abbreviations, compound words, and SEPA-specific jargon.
- **Better few-shot learning.** Larger models extract more from few-shot examples, particularly for distinguishing ambiguous categories. The per-category analysis shows the LLM already matches the ensemble on "easy" categories — a frontier model might close the gap on medium-difficulty ones.
- **Better instruction following.** The local models occasionally fail to output just a category name (1-3% parse failure for Phi-4). Frontier models would likely achieve near-perfect parse rates.

A reasonable extrapolation: a frontier model might reach 0.78-0.85 standalone F1, potentially approaching the ensemble's 0.867. But there are structural reasons to expect a ceiling:

### Why even frontier models likely can't beat the ensemble

1. **The ensemble is trained on the user's full labeled dataset (~1,500 training examples per fold).** No amount of few-shot prompting (limited by context window and cost) can substitute for supervised training on hundreds of examples per category. The ensemble learns the exact decision boundaries for this specific user's categorization scheme.

2. **Personal/idiosyncratic categories are fundamentally hard for general models.** "flora61" is a specific vendor only this user knows. "sonstiges" (miscellaneous) has no semantic pattern — it's defined by exclusion. No pre-trained model, however large, has knowledge of these personal categories. It can only rely on the few-shot examples, which provide sparse coverage.

3. **Feature engineering captures signals LLMs can't access from text alone.** The ensemble uses amount buckets, IBAN patterns, SEPA creditor IDs, and cross-feature interactions that are difficult to convey in a natural language prompt. A transaction of "-4.50 EUR" from "REWE" is obviously groceries, but the amount pattern for distinguishing "haushalt" from "lebensmittel" at the same merchant requires learned numerical boundaries.

4. **Diminishing returns on the hard tail.** The categories where the LLM struggles most (kind, haushalt, sonstiges) are hard precisely because they're ambiguous at the text level. Even a human reviewer might hesitate on some of these. More model capability helps less when the input signal is inherently ambiguous.

### Would a hybrid with a frontier model work?

Possibly — but the economics don't favor it. The ensemble already auto-categorizes ~47% of transactions with >95% confidence. Using a cloud LLM for the remaining ~53% would mean:

- **Latency:** 0.5-2s per API call vs. <1ms for the ensemble
- **Cost:** ~$0.01-0.05 per transaction (prompt is ~3,000 tokens) vs. zero for local inference
- **Privacy:** Sending transaction data (names, amounts, purposes) to a cloud API

Even if a frontier model closed the gap to ensemble parity on the uncertain tail, the marginal accuracy gain would be small (the ensemble is already decent on its uncertain predictions) while the cost and privacy trade-offs are significant.

### Bottom line

A frontier cloud model could plausibly reach 0.80-0.85 standalone F1, narrowing the gap from 19 points to perhaps 2-5 points. But it's unlikely to exceed the ensemble, and a hybrid approach faces unfavorable economics. The more promising path remains improving the ensemble itself — more training data (especially for weak categories), active learning, and better features will compound over time without adding inference cost or privacy concerns.

If local models reach 30B+ at practical speeds on Apple Silicon (e.g., Qwen3-30B-A3B MoE variants), revisiting this experiment would be worthwhile. The 3.8B-to-8B scaling trend suggests a 30B model might reach ~0.80 F1, which could make the hybrid viable at the t=0.50 threshold — but only if it outperforms the ensemble on the uncertain tail, not just overall.

## Conclusion

Local LLM classification does not improve transaction categorization accuracy in this use case. The ML ensemble (LightGBM + Naive Bayes, Macro F1 = 0.867) outperforms the best LLM (Qwen3-8B, Macro F1 = 0.674) by a wide margin, and no hybrid combination at any confidence threshold reaches the ensemble's standalone performance. Extrapolation to frontier models suggests the gap would narrow but likely not close, and the cost/privacy trade-offs of cloud inference make it impractical.

**Recommendation:** Focus improvement efforts on the existing ML pipeline — better features, more training data, active learning for weak categories — rather than adding LLM inference to the prediction path.
