#!/usr/bin/env python3
"""Experiment 3: Local LLM Classification via mlx-lm on Apple Silicon.

Tests whether a local generative LLM (prompted with category descriptions and
few-shot examples) can improve accuracy on the uncertain tail where the
ML ensemble struggles — particularly for rare/ambiguous categories.

Usage: uv run --group mlx scripts/experiment_llm_classify.py

Models tested (fastest → best):
  - Phi-4-mini-instruct-4bit (3.8B dense)
  - Qwen3-8B-4bit (8B dense, multilingual)
  - Qwen3-30B-A3B MoE (30B total, 3B active — 30B quality at 3B speed)

Evaluation modes:
  - LLM standalone: LLM predictions for all transactions
  - Ensemble standalone: ML ensemble baseline
  - Hybrid: Ensemble if confidence >= threshold, LLM otherwise

Protocol: 1x5 CV for screening all models, 5x5 CV for the best model.
"""

import copy
import json
import os
import sys
import time
import warnings
from datetime import date, datetime
from math import sqrt
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats
from sklearn.metrics import f1_score, precision_recall_fscore_support
from sklearn.model_selection import RepeatedStratifiedKFold

# Set production environment
os.environ["FAFYCAT_DB_URL"] = "sqlite:///data/fafycat_prod.db"
os.environ["FAFYCAT_ENV"] = "production"

sys.path.insert(0, str(Path(__file__).parent.parent))

from fafycat.core.config import AppConfig, MLConfig
from fafycat.core.database import CategoryORM, DatabaseManager
from fafycat.core.models import TransactionInput
from fafycat.ml.categorizer import TransactionCategorizer
from fafycat.ml.naive_bayes_classifier import NaiveBayesTextClassifier
from scripts.establish_baseline import (
    align_probas,
    load_reviewed_transactions,
)

# Suppress noisy warnings during CV
warnings.filterwarnings("ignore", category=UserWarning, module="lightgbm")
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")
warnings.filterwarnings("ignore", category=FutureWarning, module="sklearn")


# ---------------------------------------------------------------------------
# Logging helper — all output is timestamped and flushed immediately
# ---------------------------------------------------------------------------


def log(msg: str = "", indent: int = 0) -> None:
    """Print a timestamped, immediately-flushed log line."""
    ts = datetime.now().strftime("%H:%M:%S")
    prefix = "  " * indent
    print(f"[{ts}] {prefix}{msg}", flush=True)


def log_banner(title: str) -> None:
    """Print a prominent banner."""
    line = "=" * 60
    log(line)
    log(title)
    log(line)


def log_section(title: str) -> None:
    """Print a section divider."""
    log(f"--- {title} ---")


def fmt_elapsed(seconds: float) -> str:
    """Format elapsed time as human-readable string."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h{m:02d}m"


# ---------------------------------------------------------------------------
# Models to test
# ---------------------------------------------------------------------------

MODELS = [
    {
        "name": "phi-4-mini",
        "repo": "mlx-community/Phi-4-mini-instruct-4bit",
        "params": "3.8B dense",
    },
    {
        "name": "qwen3-8b",
        "repo": "mlx-community/Qwen3-8B-4bit",
        "params": "8B dense",
    },
    # {
    #     "name": "qwen3-30b-a3b",
    #     "repo": "Qwen/Qwen3-30B-A3B-MLX-4bit",
    #     "params": "30B MoE (3B active)",
    # },
]

# ---------------------------------------------------------------------------
# Category descriptions (German, to match input language)
# ---------------------------------------------------------------------------

CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "auswaertsessen": "Restaurants, Cafés, Lieferdienste, auswärts essen gehen",
    "bargeld": "Bargeldabhebungen am Geldautomaten (ATM)",
    "beitragsservice": "Rundfunkbeitrag, GEZ, ARD/ZDF Beitragsservice",
    "buecher": "Bücher, E-Books, Hörbücher (z.B. Thalia, Amazon Kindle)",
    "david work travel": "Geschäftsreisen und Dienstreisen (Bahn, Flug, Hotel für Arbeit)",
    "dsl": "Internet- und Telefonanbieter, DSL, Mobilfunkvertrag",
    "einkommen-p2": "Zweites Gehalt/Einkommen, Lohn der zweiten Person im Haushalt",
    "flora61": "Flora 61 — spezifischer Laden oder Dienstleister",
    "haushalt": "Haushaltswaren, Reinigungsmittel, Haushaltsgeräte, Drogerie",
    "investieren": "Wertpapierkäufe, ETF-Sparpläne, Aktien, Depot-Transaktionen",
    "kind": "Ausgaben für Kinder: Kita, Spielzeug, Kinderkleidung, Babybedarf",
    "kindergeld": "Kindergeld-Eingang vom Staat",
    "kleidung": "Kleidung und Schuhe (H&M, Zalando, etc.)",
    "lebensmittel": "Supermarkt, Lebensmitteleinkäufe (REWE, Edeka, Aldi, Lidl)",
    "media-abos": "Streaming-Abos, Zeitschriften, digitale Abonnements (Netflix, Spotify)",
    "miete": "Monatliche Mietzahlung, Warmmiete, Kaltmiete",
    "mobilitaet": "ÖPNV, Tankstelle, Carsharing, Fahrrad, Mobilität allgemein",
    "sonstiges": "Sonstige Ausgaben die in keine andere Kategorie passen",
    "sparen": "Sparüberweisungen auf Tagesgeld- oder Sparkonto",
    "sport": "Fitnessstudio, Sportverein, Sportausrüstung",
    "steuer": "Steuerzahlungen, Finanzamt, Steuererklärung, Steuerberater",
    "strom": "Strom- und Gasanbieter, Energiekosten",
    "taschengeld": "Taschengeld-Überweisungen",
    "technik": "Elektronik, Computer, Software, IT-Zubehör",
    "urlaub&freizeit": "Urlaub, Reisen (privat), Freizeitaktivitäten, Ausflüge, Kino",
    "wohnung": "Wohnungseinrichtung, Möbel, Renovierung, Baumarkt",
}


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def build_system_prompt(categories: list[str]) -> str:
    """Build the German system prompt with category descriptions."""
    cat_lines = []
    for cat in sorted(categories):
        desc = CATEGORY_DESCRIPTIONS.get(cat, "")
        if desc:
            cat_lines.append(f"- {cat}: {desc}")
        else:
            cat_lines.append(f"- {cat}")

    return (
        "Du bist ein Experte für die Kategorisierung von deutschen Banktransaktionen.\n"
        "Gegeben eine Banktransaktion, ordne sie einer der folgenden Kategorien zu:\n\n"
        + "\n".join(cat_lines)
        + "\n\nAntworte NUR mit dem Kategorienamen, nichts anderes."
    )


def build_few_shot_examples(
    transactions: list[TransactionInput],
    labels: np.ndarray,
    cat_names: dict[int, str],
    n_per_category: int = 2,
) -> str:
    """Select few-shot examples: shortest text per category (most prototypical).

    Returns formatted string of examples for the prompt.
    """
    # Group by category
    by_category: dict[str, list[TransactionInput]] = {}
    for txn, label in zip(transactions, labels, strict=True):
        cat_name = cat_names.get(int(label), "")
        if not cat_name:
            continue
        by_category.setdefault(cat_name, []).append(txn)

    examples = []
    for cat_name in sorted(by_category.keys()):
        txns = by_category[cat_name]
        # Sort by combined text length (shortest = cleanest, most prototypical)
        txns_sorted = sorted(txns, key=lambda t: len(f"{t.name} {t.purpose}"))
        for txn in txns_sorted[:n_per_category]:
            examples.append(format_transaction_with_label(txn, cat_name))

    return "\n\n".join(examples)


def format_transaction(txn: TransactionInput) -> str:
    """Format a transaction for the LLM prompt."""
    parts = [f"Name: {txn.name}"]
    if txn.purpose:
        parts.append(f"Verwendungszweck: {txn.purpose}")
    parts.append(f"Betrag: {txn.amount:.2f} EUR")
    return "\n".join(parts)


def format_transaction_with_label(txn: TransactionInput, category: str) -> str:
    """Format a transaction with its label for few-shot examples."""
    return f"{format_transaction(txn)}\nKategorie: {category}"


def build_user_prompt(txn: TransactionInput) -> str:
    """Build the user prompt for a single transaction."""
    return format_transaction(txn) + "\nKategorie:"


# ---------------------------------------------------------------------------
# LLM classification
# ---------------------------------------------------------------------------


class LLMClassifier:
    """Wrapper around mlx-lm for transaction classification.

    Uses KV cache prefilling to avoid redundant processing of the shared prompt
    prefix (system prompt + few-shot examples) across transactions. The shared
    prefix is prefilled once, then deep-copied for each transaction so only the
    transaction-specific suffix needs to be processed.
    """

    def __init__(self, model_repo: str, categories: list[str]):
        self.model_repo = model_repo
        self.categories = sorted(categories)
        self.categories_lower = {c.lower(): c for c in self.categories}
        self.model: Any = None
        self.tokenizer: Any = None
        self.system_prompt = build_system_prompt(self.categories)
        self.few_shot_text: str | None = None

        # Prompt cache state (set by _prefill_cache)
        self._cached_prefix: list | None = None
        self._prefix_len: int = 0

        # Stats
        self.parse_successes = 0
        self.parse_failures = 0
        self.retry_successes = 0

    def load_model(self) -> None:
        """Load the MLX model and tokenizer."""
        from mlx_lm import load

        log(f"Loading model: {self.model_repo}", indent=1)
        start = time.time()
        self.model, self.tokenizer = load(self.model_repo)
        log(f"Model loaded in {fmt_elapsed(time.time() - start)}", indent=1)

    def set_few_shot_examples(self, examples_text: str) -> None:
        """Set the few-shot examples string (from training fold)."""
        self.few_shot_text = examples_text
        # Invalidate any existing cache since the few-shot examples changed
        self._cached_prefix = None
        self._prefix_len = 0

    def _build_prefix_messages(self) -> list[dict[str, str]]:
        """Build the shared prefix messages (system + few-shot + assistant ack)."""
        messages = [{"role": "system", "content": self.system_prompt}]

        if self.few_shot_text:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Hier sind einige Beispiele zur Orientierung:\n\n"
                        + self.few_shot_text
                        + "\n\nJetzt klassifiziere die folgende Transaktion:"
                    ),
                }
            )
            messages.append(
                {
                    "role": "assistant",
                    "content": "Verstanden. Ich werde die Transaktion klassifizieren.",
                }
            )

        return messages

    def _build_messages(self, txn: TransactionInput, retry: bool = False) -> list[dict[str, str]]:
        """Build the chat messages for the LLM."""
        messages = self._build_prefix_messages()

        user_content = build_user_prompt(txn)
        if retry:
            user_content += (
                "\n\nWICHTIG: Antworte NUR mit einem der folgenden Kategorienamen, "
                "nichts anderes:\n" + ", ".join(self.categories)
            )
        messages.append({"role": "user", "content": user_content})

        return messages

    def _apply_template(
        self, messages: list[dict[str, str]], *, tokenize: bool = True, add_generation_prompt: bool = True
    ) -> str | list[int]:
        """Apply chat template with thinking mode disabled.

        Qwen3 models default to "thinking mode" which generates verbose
        chain-of-thought before the answer. Passing enable_thinking=False
        suppresses this. The kwarg is silently ignored by non-Qwen tokenizers.
        """
        return self.tokenizer.apply_chat_template(
            messages,
            tokenize=tokenize,
            add_generation_prompt=add_generation_prompt,
            enable_thinking=False,
        )

    def _find_prefix_length(self) -> int:
        """Find the shared prefix token count by comparing two dummy tokenizations.

        Uses two dummy user messages with different content to find exactly where
        the shared prefix ends (at the last user message boundary).
        """
        prefix_messages = self._build_prefix_messages()

        # Two dummy messages that differ from the first character
        full_a = self._apply_template(
            prefix_messages + [{"role": "user", "content": "AAAAAA"}],
            tokenize=True,
            add_generation_prompt=True,
        )
        full_b = self._apply_template(
            prefix_messages + [{"role": "user", "content": "ZZZZZZ"}],
            tokenize=True,
            add_generation_prompt=True,
        )

        common_len = 0
        for a, b in zip(full_a, full_b, strict=False):
            if a == b:
                common_len += 1
            else:
                break

        return common_len

    def _prefill_cache(self) -> None:
        """Prefill the KV cache with the shared prompt prefix.

        Tokenizes the shared prefix (system prompt + few-shot examples + assistant
        acknowledgement + user turn start), runs it through the model to build the
        KV cache, then stores the cache for reuse via deep-copy per transaction.
        """
        import mlx.core as mx
        from mlx_lm.models.cache import make_prompt_cache

        self._prefix_len = self._find_prefix_length()

        # Get the actual prefix tokens from a dummy full tokenization
        prefix_messages = self._build_prefix_messages()
        dummy_tokens = self._apply_template(
            prefix_messages + [{"role": "user", "content": "AAAAAA"}],
            tokenize=True,
            add_generation_prompt=True,
        )
        prefix_tokens = mx.array(dummy_tokens[: self._prefix_len])

        # Create and fill cache
        cache = make_prompt_cache(self.model)
        step_size = 2048
        processed = 0
        while processed < self._prefix_len:
            chunk_size = min(step_size, self._prefix_len - processed)
            chunk = prefix_tokens[processed : processed + chunk_size]
            self.model(chunk[None], cache=cache)
            mx.eval([c.state for c in cache])
            processed += chunk_size

        self._cached_prefix = cache
        log(f"Prompt cache prefilled: {self._prefix_len} tokens", indent=2)

    def _parse_response(self, response: str) -> str | None:
        """Parse the LLM response to extract a valid category name.

        Returns category name or None if parsing fails.
        """
        text = response.strip().strip('"').strip("'").strip()

        # 1. Direct match (case-insensitive)
        if text.lower() in self.categories_lower:
            return self.categories_lower[text.lower()]

        # 2. Check if response contains a valid category name
        text_lower = text.lower()
        for cat_lower, cat in self.categories_lower.items():
            if cat_lower in text_lower:
                return cat

        # 3. Try JSON parse
        if "{" in text:
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    for val in parsed.values():
                        if isinstance(val, str) and val.lower() in self.categories_lower:
                            return self.categories_lower[val.lower()]
            except json.JSONDecodeError:
                pass

        return None

    @staticmethod
    def _greedy_sampler(logits):
        """Greedy sampler (argmax, temperature=0 equivalent)."""
        import mlx.core as mx

        return mx.argmax(logits, axis=-1)

    def _generate_with_cache(self, txn: TransactionInput) -> str:
        """Generate a response using the prefilled KV cache.

        Deep-copies the prefilled cache, tokenizes only the transaction-specific
        suffix, and generates using cached prefix + suffix tokens.
        """
        from mlx_lm import generate

        messages = self._build_messages(txn)
        full_tokens = self._apply_template(messages, tokenize=True, add_generation_prompt=True)
        suffix_tokens = full_tokens[self._prefix_len :]

        cache_copy = copy.deepcopy(self._cached_prefix)
        return generate(
            self.model,
            self.tokenizer,
            prompt=suffix_tokens,
            prompt_cache=cache_copy,
            max_tokens=30,
            sampler=self._greedy_sampler,
            verbose=False,
        )

    def classify_one(self, txn: TransactionInput) -> tuple[str | None, str]:
        """Classify a single transaction.

        Uses the prefilled KV cache for the primary attempt to avoid redundant
        processing of the shared prefix. Falls back to uncached generation for
        retries (different prompt structure, and retries are rare).

        Returns (category_name_or_None, raw_response).
        """
        from mlx_lm import generate

        # Primary attempt: use cached prefix
        if self._cached_prefix is not None:
            response = self._generate_with_cache(txn)
        else:
            messages = self._build_messages(txn)
            prompt = self._apply_template(messages, tokenize=False, add_generation_prompt=True)
            response = generate(
                self.model, self.tokenizer, prompt=prompt, max_tokens=30, sampler=self._greedy_sampler, verbose=False
            )

        category = self._parse_response(response)

        if category is not None:
            self.parse_successes += 1
            return category, response

        # Retry with explicit correction prompt (uncached — different prefix, rare path)
        messages_retry = self._build_messages(txn, retry=True)
        prompt_retry = self._apply_template(messages_retry, tokenize=False, add_generation_prompt=True)
        response_retry = generate(
            self.model, self.tokenizer, prompt=prompt_retry, max_tokens=30, sampler=self._greedy_sampler, verbose=False
        )

        category_retry = self._parse_response(response_retry)
        if category_retry is not None:
            self.retry_successes += 1
            return category_retry, response_retry

        self.parse_failures += 1
        return None, response

    def classify_batch(
        self,
        transactions: list[TransactionInput],
        progress_every: int = 25,
    ) -> list[tuple[str | None, str]]:
        """Classify a batch of transactions with progress reporting.

        Prefills the KV cache with the shared prefix before processing
        transactions, so each transaction only processes its unique suffix.
        """
        # Prefill the KV cache for this batch
        self._prefill_cache()

        results = []
        total = len(transactions)
        start = time.time()

        for i, txn in enumerate(transactions):
            result = self.classify_one(txn)
            results.append(result)

            if (i + 1) % progress_every == 0 or (i + 1) == total:
                elapsed = time.time() - start
                rate = (i + 1) / elapsed
                eta = (total - i - 1) / rate if rate > 0 else 0
                total_attempts = self.parse_successes + self.retry_successes + self.parse_failures
                successes = self.parse_successes + self.retry_successes
                parse_rate = successes / total_attempts * 100 if total_attempts else 0
                pct = (i + 1) / total * 100
                log(
                    f"LLM {i + 1}/{total} ({pct:.0f}%) | "
                    f"{rate:.1f} txn/s | ETA {fmt_elapsed(eta)} | "
                    f"parse {parse_rate:.0f}%",
                    indent=2,
                )

        return results

    def get_stats(self) -> dict[str, Any]:
        """Return parse statistics."""
        total = self.parse_successes + self.retry_successes + self.parse_failures
        return {
            "total": total,
            "parse_successes": self.parse_successes,
            "retry_successes": self.retry_successes,
            "parse_failures": self.parse_failures,
            "parse_rate": (self.parse_successes + self.retry_successes) / total * 100 if total > 0 else 0,
        }

    def reset_stats(self) -> None:
        """Reset parse statistics between folds."""
        self.parse_successes = 0
        self.parse_failures = 0
        self.retry_successes = 0


# ---------------------------------------------------------------------------
# Ensemble helpers (reused from establish_baseline.py)
# ---------------------------------------------------------------------------


def get_lgbm_probas(categorizer: TransactionCategorizer, test_txns: list[TransactionInput]) -> np.ndarray:
    """Get full probability vectors from a fitted LightGBM categorizer."""
    import pandas as pd

    features_list = categorizer.feature_extractor.extract_batch_features(test_txns)
    test_df = pd.DataFrame(features_list)
    X_test = categorizer._prepare_features(test_df, fit=False)
    if categorizer.calibrated_classifier is not None:
        return categorizer.calibrated_classifier.predict_proba(X_test)
    return categorizer.classifier.predict_proba(X_test)


def train_ensemble_fold(
    train_txns: list[TransactionInput],
    train_labels: np.ndarray,
    test_txns: list[TransactionInput],
    unique_classes: np.ndarray,
    class_to_idx: dict[int, int],
    session,
    config: MLConfig,
    fold_idx: int,
) -> np.ndarray:
    """Train ensemble on a fold and return aligned probability matrix for test set."""
    # LightGBM
    log("Fitting LightGBM...", indent=2)
    lgbm = TransactionCategorizer(session, config)
    lgbm.fit(train_txns, train_labels)
    lgbm_probas = get_lgbm_probas(lgbm, test_txns)
    lgbm_aligned = align_probas(lgbm_probas, lgbm.classes_, unique_classes)

    # Naive Bayes
    log("Fitting Naive Bayes...", indent=2)
    nb = NaiveBayesTextClassifier(
        alpha=config.nb_alpha,
        use_complement=config.nb_use_complement,
        max_features=config.nb_max_features,
    )
    nb.fit(train_txns, train_labels)
    nb_probas = nb.predict_proba(test_txns)
    nb_aligned = align_probas(nb_probas, nb.classes_, unique_classes)

    # Optimize ensemble weight on sub-validation split
    log("Optimizing ensemble weights...", indent=2)
    from sklearn.model_selection import train_test_split

    try:
        sub_train, sub_val, sub_train_y, sub_val_y = train_test_split(
            train_txns, train_labels, test_size=0.2, stratify=train_labels, random_state=42 + fold_idx
        )
    except ValueError:
        log("Stratified split failed, using default w=0.7", indent=2)
        return 0.7 * lgbm_aligned + 0.3 * nb_aligned

    sub_val_enc = np.array([class_to_idx[int(lbl)] for lbl in sub_val_y])

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

    best_w = 0.7
    best_score = -1.0
    for w in np.arange(0.3, 0.85, 0.05):
        combined = float(w) * lgbm_sub_aligned + (1 - float(w)) * nb_sub_aligned
        preds = np.argmax(combined, axis=1)
        score = float(f1_score(sub_val_enc, preds, average="macro", zero_division=0))
        if score > best_score:
            best_score = score
            best_w = float(w)

    log(f"Ensemble weight: LGB={best_w:.2f} NB={1 - best_w:.2f}", indent=2)
    return best_w * lgbm_aligned + (1 - best_w) * nb_aligned


# ---------------------------------------------------------------------------
# CV evaluation
# ---------------------------------------------------------------------------


def run_cv_for_model(
    model_info: dict[str, str],
    txn_inputs: list[TransactionInput],
    labels: np.ndarray,
    cat_names: dict[int, str],
    session,
    config: MLConfig,
    n_repeats: int = 1,
) -> dict[str, Any]:
    """Run repeated stratified k-fold CV for a single LLM model.

    Evaluates 3 modes: LLM standalone, ensemble standalone, hybrid.
    Also sweeps the hybrid handoff threshold.
    """
    log_banner(f"Model: {model_info['name']} ({model_info['params']})")
    log(f"CV: {n_repeats}x5 stratified k-fold")

    # Initialize LLM
    categories = sorted(set(cat_names.values()))
    llm = LLMClassifier(model_info["repo"], categories)
    llm.load_model()

    # Class encoding
    txn_array = np.array(txn_inputs, dtype=object)
    unique_classes = np.sort(np.unique(labels))
    n_classes = len(unique_classes)
    class_to_idx = {int(c): i for i, c in enumerate(unique_classes)}

    rskf = RepeatedStratifiedKFold(n_splits=5, n_repeats=n_repeats, random_state=42)
    n_total_folds = rskf.get_n_splits()

    # Accumulators for each mode
    modes = ["llm_standalone", "ensemble_standalone", "hybrid_0.95"]
    accumulators: dict[str, dict[str, list]] = {
        mode: {"fold_scores": [], "all_true": [], "all_pred": []} for mode in modes
    }

    # Threshold sweep accumulators
    sweep_thresholds = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
    threshold_results: dict[str, dict[str, list]] = {f"{t:.2f}": {"fold_scores": []} for t in sweep_thresholds}

    all_parse_stats: list[dict] = []
    total_start = time.time()

    for fold_idx, (train_idx, test_idx) in enumerate(rskf.split(txn_array, labels)):
        fold_start = time.time()
        elapsed_total = time.time() - total_start
        log_section(
            f"Fold {fold_idx + 1}/{n_total_folds} [{model_info['name']}] (elapsed: {fmt_elapsed(elapsed_total)})"
        )

        train_txns = txn_array[train_idx].tolist()
        test_txns = txn_array[test_idx].tolist()
        train_labels = labels[train_idx]
        test_labels = labels[test_idx]
        test_encoded = np.array([class_to_idx[int(lbl)] for lbl in test_labels])

        log(f"Train: {len(train_txns)}, Test: {len(test_txns)}", indent=1)

        # 1. Build few-shot examples from training set
        log("Building few-shot examples...", indent=1)
        few_shot_text = build_few_shot_examples(train_txns, train_labels, cat_names)
        llm.set_few_shot_examples(few_shot_text)
        llm.reset_stats()

        # 2. Train ensemble on training set
        log("Training ensemble (LightGBM + NB + weight opt)...", indent=1)
        ens_start = time.time()
        ens_probas = train_ensemble_fold(
            train_txns,
            train_labels,
            test_txns,
            unique_classes,
            class_to_idx,
            session,
            config,
            fold_idx,
        )
        ens_preds = np.argmax(ens_probas, axis=1)
        ens_confidences = np.max(ens_probas, axis=1)
        ens_f1 = float(f1_score(test_encoded, ens_preds, average="macro", zero_division=0))
        log(f"Ensemble done in {fmt_elapsed(time.time() - ens_start)}, F1={ens_f1:.4f}", indent=1)

        # 3. Classify ALL test transactions with LLM
        log(f"Classifying {len(test_txns)} transactions with LLM...", indent=1)
        llm_start = time.time()
        llm_results = llm.classify_batch(test_txns)
        llm_elapsed = time.time() - llm_start

        # Convert LLM predictions to encoded indices
        llm_preds_encoded = np.full(len(test_txns), -1, dtype=int)
        cat_to_idx = {cat_names[int(c)]: i for i, c in enumerate(unique_classes)}

        for i, (cat_name, _raw) in enumerate(llm_results):
            if cat_name is not None and cat_name in cat_to_idx:
                llm_preds_encoded[i] = cat_to_idx[cat_name]
            else:
                # Parse failure -> fallback to ensemble prediction
                llm_preds_encoded[i] = ens_preds[i]

        llm_f1 = float(f1_score(test_encoded, llm_preds_encoded, average="macro", zero_division=0))
        parse_stats = llm.get_stats()
        all_parse_stats.append(parse_stats)
        pr = parse_stats["parse_rate"]
        log(f"LLM done in {fmt_elapsed(llm_elapsed)}, F1={llm_f1:.4f}, parse={pr:.1f}%", indent=1)

        # 4. Hybrid: ensemble if confidence >= 0.95, LLM otherwise
        hybrid_preds = np.where(ens_confidences >= 0.95, ens_preds, llm_preds_encoded)
        hybrid_f1 = float(f1_score(test_encoded, hybrid_preds, average="macro", zero_division=0))

        n_ens_used = int((ens_confidences >= 0.95).sum())
        n_llm_used = len(test_txns) - n_ens_used

        fold_time = time.time() - fold_start
        log(
            f"FOLD RESULT: Ens={ens_f1:.4f} | LLM={llm_f1:.4f} | "
            f"Hybrid={hybrid_f1:.4f} (ens:{n_ens_used}/llm:{n_llm_used}) | "
            f"{fmt_elapsed(fold_time)}",
            indent=1,
        )

        # Accumulate results
        accumulators["llm_standalone"]["fold_scores"].append(llm_f1)
        accumulators["llm_standalone"]["all_true"].append(test_encoded)
        accumulators["llm_standalone"]["all_pred"].append(llm_preds_encoded)

        accumulators["ensemble_standalone"]["fold_scores"].append(ens_f1)
        accumulators["ensemble_standalone"]["all_true"].append(test_encoded)
        accumulators["ensemble_standalone"]["all_pred"].append(ens_preds)

        accumulators["hybrid_0.95"]["fold_scores"].append(hybrid_f1)
        accumulators["hybrid_0.95"]["all_true"].append(test_encoded)
        accumulators["hybrid_0.95"]["all_pred"].append(hybrid_preds)

        # Threshold sweep
        for t in sweep_thresholds:
            swept_preds = np.where(ens_confidences >= t, ens_preds, llm_preds_encoded)
            swept_f1 = float(f1_score(test_encoded, swept_preds, average="macro", zero_division=0))
            threshold_results[f"{t:.2f}"]["fold_scores"].append(swept_f1)

        # Running average after each fold
        avg_ens = np.mean(accumulators["ensemble_standalone"]["fold_scores"])
        avg_llm = np.mean(accumulators["llm_standalone"]["fold_scores"])
        avg_hyb = np.mean(accumulators["hybrid_0.95"]["fold_scores"])
        log(
            f"Running avg: Ens={avg_ens:.4f} | LLM={avg_llm:.4f} | Hybrid={avg_hyb:.4f}",
            indent=1,
        )

    total_time = time.time() - total_start
    log_banner(f"Model {model_info['name']} complete in {fmt_elapsed(total_time)}")

    # Aggregate results for each mode
    results: dict[str, Any] = {
        "model": model_info,
        "cv_scheme": f"{n_repeats}x5 repeated stratified k-fold",
        "total_time_minutes": round(total_time / 60, 1),
    }

    for mode, acc in accumulators.items():
        scores = np.array(acc["fold_scores"])
        mean_score = float(scores.mean())
        std_score = float(scores.std(ddof=1))
        n_folds = len(acc["fold_scores"])
        corrected_se = std_score * sqrt(1 / n_folds + 0.2 / 0.8)
        t_crit = float(stats.t.ppf(0.975, df=n_folds - 1))
        ci_low = mean_score - t_crit * corrected_se
        ci_high = mean_score + t_crit * corrected_se

        y_true_all = np.concatenate(acc["all_true"])
        y_pred_all = np.concatenate(acc["all_pred"])
        macro_f1_agg = float(f1_score(y_true_all, y_pred_all, average="macro", zero_division=0))
        weighted_f1_agg = float(f1_score(y_true_all, y_pred_all, average="weighted", zero_division=0))

        # Per-category F1
        per_cat_f1 = {}
        _, _, f1_per, support = precision_recall_fscore_support(
            y_true_all, y_pred_all, labels=list(range(n_classes)), average=None, zero_division=0
        )
        for i, cls in enumerate(unique_classes):
            cat_name = cat_names.get(int(cls), f"category_{cls}")
            per_cat_f1[cat_name] = round(float(f1_per[i]), 4)

        results[mode] = {
            "macro_f1": {
                "mean": round(mean_score, 4),
                "std": round(std_score, 4),
                "ci_95": [round(ci_low, 4), round(ci_high, 4)],
            },
            "macro_f1_aggregate": round(macro_f1_agg, 4),
            "weighted_f1": round(weighted_f1_agg, 4),
            "fold_scores": [round(s, 4) for s in acc["fold_scores"]],
            "per_category_f1": per_cat_f1,
        }

    # Threshold sweep summary
    sweep_summary = {}
    for t_str, t_acc in threshold_results.items():
        scores = np.array(t_acc["fold_scores"])
        sweep_summary[t_str] = {
            "mean_f1": round(float(scores.mean()), 4),
            "std_f1": round(float(scores.std(ddof=1)), 4),
        }
    results["threshold_sweep"] = sweep_summary

    # Parse statistics
    total_parse = sum(s["total"] for s in all_parse_stats)
    total_success = sum(s["parse_successes"] + s["retry_successes"] for s in all_parse_stats)
    total_retry = sum(s["retry_successes"] for s in all_parse_stats)
    total_fail = sum(s["parse_failures"] for s in all_parse_stats)
    results["parse_stats"] = {
        "total_classifications": total_parse,
        "direct_parse_successes": total_parse - total_retry - total_fail,
        "retry_successes": total_retry,
        "parse_failures": total_fail,
        "overall_parse_rate": round(total_success / total_parse * 100, 1) if total_parse > 0 else 0,
    }

    return results


def run_sanity_check(
    model_info: dict[str, str],
    txn_inputs: list[TransactionInput],
    labels: np.ndarray,
    cat_names: dict[int, str],
) -> bool:
    """Quick sanity test: classify 10 transactions and check parse quality."""
    log_banner(f"Sanity check: {model_info['name']}")

    categories = sorted(set(cat_names.values()))
    llm = LLMClassifier(model_info["repo"], categories)
    llm.load_model()

    # Use first 100 transactions for few-shot context
    few_shot = build_few_shot_examples(txn_inputs[:100], labels[:100], cat_names, n_per_category=2)
    llm.set_few_shot_examples(few_shot)

    # Pick 10 diverse transactions
    sample_indices = np.linspace(0, len(txn_inputs) - 1, 10, dtype=int)
    sample_txns = [txn_inputs[i] for i in sample_indices]
    sample_labels = [cat_names.get(int(labels[i]), "?") for i in sample_indices]

    results = llm.classify_batch(sample_txns, progress_every=5)

    correct = 0
    for i, ((pred_cat, raw), true_cat) in enumerate(zip(results, sample_labels, strict=True)):
        status = "OK" if pred_cat == true_cat else ("WRONG" if pred_cat else "FAIL")
        if pred_cat == true_cat:
            correct += 1
        log(f"[{i + 1}] true={true_cat:<20} pred={str(pred_cat):<20} [{status}]  raw={raw[:60]}", indent=1)

    stats = llm.get_stats()
    log(f"Parse rate: {stats['parse_rate']:.0f}%  Accuracy: {correct}/10")

    success = stats["parse_rate"] >= 80
    if success:
        log("PASS: Parse rate OK, proceeding with CV")
    else:
        log("FAIL: Parse rate too low, skipping this model")

    return success


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    log_banner("Experiment 3: Local LLM Classification (mlx-lm)")

    config = AppConfig()
    config.ensure_dirs()
    config.ml.lgbm_params["verbose"] = -1
    config.ml.lgbm_params["n_jobs"] = 8

    db_manager = DatabaseManager(config)

    with db_manager.get_session() as session:
        # Load data
        log("[1/4] Loading data...")
        txn_inputs, labels, df = load_reviewed_transactions(session)

        # Category name lookup
        unique_cats = np.unique(labels)
        cat_names: dict[int, str] = {}
        for cid in unique_cats:
            cat = session.query(CategoryORM).filter(CategoryORM.id == int(cid)).first()
            if cat:
                cat_names[int(cid)] = cat.name

        # Phase 1: Sanity check with fastest model
        log("[2/4] Sanity check with Phi-4-mini...")
        sanity_ok = run_sanity_check(MODELS[0], txn_inputs, labels, cat_names)

        if not sanity_ok:
            log("Sanity check failed. Aborting experiment.")
            return

        # Phase 2: 1x5 CV screening for all models
        log("[3/4] Running 1x5 CV screening for all 3 models...")
        all_results: dict[str, Any] = {
            "metadata": {
                "date": str(date.today()),
                "experiment": "llm_classification",
                "n_transactions": len(txn_inputs),
                "n_categories": len(unique_cats),
                "baselines": {
                    "lightgbm_macro_f1": 0.851,
                    "ensemble_macro_f1": 0.855,
                },
            },
            "models": {},
        }

        best_model = None
        best_hybrid_f1 = 0.0

        for model_idx, model_info in enumerate(MODELS):
            log(f"Starting model {model_idx + 1}/{len(MODELS)}: {model_info['name']}")
            result = run_cv_for_model(
                model_info,
                txn_inputs,
                labels,
                cat_names,
                session,
                config.ml,
                n_repeats=1,
            )
            all_results["models"][model_info["name"]] = result

            # Save intermediate results
            out_path = Path("scratch_pads/experiment_llm_results.json")
            with open(out_path, "w") as f:
                json.dump(all_results, f, indent=2)
            log(f"Intermediate results saved to {out_path}")

            # Check if this is the best model
            hybrid_f1 = result["hybrid_0.95"]["macro_f1"]["mean"]
            if hybrid_f1 > best_hybrid_f1:
                best_hybrid_f1 = hybrid_f1
                best_model = model_info

            # Check parse failure rate
            parse_rate = result["parse_stats"]["overall_parse_rate"]
            if parse_rate < 95:
                log(f"WARNING: Parse rate {parse_rate:.1f}% < 95% for {model_info['name']}")

        # Phase 3: Summary and 5x5 decision
        log_banner("SCREENING SUMMARY")

        log(f"{'Model':<20} {'LLM F1':>8} {'Ens F1':>8} {'Hybrid F1':>10} {'Parse%':>8} {'Time':>8}")
        log("-" * 66)
        for name, res in all_results["models"].items():
            llm_f1 = res["llm_standalone"]["macro_f1"]["mean"]
            ens_f1 = res["ensemble_standalone"]["macro_f1"]["mean"]
            hyb_f1 = res["hybrid_0.95"]["macro_f1"]["mean"]
            parse_pct = res["parse_stats"]["overall_parse_rate"]
            t_min = res["total_time_minutes"]
            log(f"{name:<20} {llm_f1:>8.4f} {ens_f1:>8.4f} {hyb_f1:>10.4f} {parse_pct:>7.1f}% {t_min:>7.1f}m")

        # Threshold sweep summary for best model
        if best_model:
            best_res = all_results["models"][best_model["name"]]
            log(f"\nThreshold sweep for {best_model['name']}:")
            log(f"{'Threshold':>10} {'Mean F1':>8}")
            log("-" * 20)
            for t_str, t_val in best_res["threshold_sweep"].items():
                log(f"{t_str:>10} {t_val['mean_f1']:>8.4f}")

        # Decision: run 5x5 CV?
        run_5x5 = best_hybrid_f1 > 0.860  # Meaningful improvement over 0.855

        if run_5x5 and best_model:
            log(f"[4/4] Running 5x5 CV for best model: {best_model['name']}...")
            result_5x5 = run_cv_for_model(
                best_model,
                txn_inputs,
                labels,
                cat_names,
                session,
                config.ml,
                n_repeats=5,
            )
            all_results["best_model_5x5"] = result_5x5

            # Statistical significance test
            ens_scores = result_5x5["ensemble_standalone"]["fold_scores"]
            hyb_scores = result_5x5["hybrid_0.95"]["fold_scores"]

            if len(ens_scores) == len(hyb_scores):
                t_stat, p_val = stats.ttest_rel(hyb_scores, ens_scores)
                all_results["significance_test"] = {
                    "test": "paired t-test (hybrid vs ensemble)",
                    "t_statistic": round(float(t_stat), 4),
                    "p_value": round(float(p_val), 4),
                    "significant_0.05": p_val < 0.05,
                }
                log(f"Paired t-test (hybrid vs ensemble): t={t_stat:.3f}, p={p_val:.4f}")
        else:
            log("[4/4] Skipping 5x5 CV (hybrid F1 not above 0.860)")

        # Save final results
        out_path = Path("scratch_pads/experiment_llm_results.json")
        with open(out_path, "w") as f:
            json.dump(all_results, f, indent=2)
        log(f"Results saved to {out_path}")

        # Final decision
        log_banner("DECISION")

        if best_hybrid_f1 >= 0.870:
            log(f"Hybrid Macro F1 = {best_hybrid_f1:.4f} >= 0.870")
            log("-> INTEGRATE: LLM hybrid improves production accuracy significantly.")
        elif best_hybrid_f1 > 0.855:
            log(f"Hybrid Macro F1 = {best_hybrid_f1:.4f} > 0.855 (modest improvement)")
            log("-> CONSIDER: Small improvement. Check per-category gains on weak classes.")
        else:
            log(f"Hybrid Macro F1 = {best_hybrid_f1:.4f} <= 0.855")
            log("-> SKIP: No improvement over ensemble. LLM not worth the latency cost.")


if __name__ == "__main__":
    main()
