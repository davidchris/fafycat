"""Feature extraction for transaction categorization."""

import re
from typing import Any

import numpy as np

from ..core.models import TransactionInput


class MerchantCleaner:
    """Clean and normalize merchant names."""

    def __init__(self):
        self.patterns = [
            r"\d{4}\.\d{2}\.\d{2}.*",  # Dates
            r"//.*",  # Location info after //
            r"\b(DE|Berlin|München|Hamburg|Köln|Frankfurt|Stuttgart)\b.*",  # Cities/countries
            r"Folgenr\.\d+.*",  # Transaction numbers
            r"\bNR\.\d+.*",  # Reference numbers
            r"\d{2}:\d{2}:\d{2}.*",  # Times
            r"\*+.*",  # Everything after asterisks
        ]

    def clean(self, merchant_name: str) -> str:
        """Clean and normalize merchant name."""
        if not merchant_name:
            return ""

        cleaned = merchant_name.strip()

        # Remove patterns
        for pattern in self.patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

        # Normalize whitespace and case
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = cleaned.strip().upper()

        # Remove common prefixes/suffixes
        prefixes_to_remove = ["EC ", "KARTE NR", "FOLGENR"]
        for prefix in prefixes_to_remove:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix) :].strip()

        return cleaned


class TextPreprocessor:
    """Process text fields for NLP features."""

    def __init__(self):
        self.stopwords = {
            "und",
            "oder",
            "der",
            "die",
            "das",
            "ein",
            "eine",
            "einen",
            "vom",
            "zum",
            "zur",
            "am",
            "im",
            "an",
            "auf",
            "bei",
            "mit",
        }

    def process(self, text: str) -> str:
        """Process text for feature extraction."""
        if not text:
            return ""

        # Convert to lowercase
        text = text.lower()

        # Remove special characters but keep spaces
        text = re.sub(r"[^\w\s]", " ", text)

        # Remove extra whitespace
        text = re.sub(r"\s+", " ", text)

        # Remove stopwords
        words = text.split()
        words = [word for word in words if word not in self.stopwords and len(word) > 2]

        return " ".join(words)


class FeatureExtractor:
    """Extract features from transactions for ML model."""

    def __init__(self):
        self.merchant_cleaner = MerchantCleaner()
        self.text_preprocessor = TextPreprocessor()

    def extract_features(self, transaction: TransactionInput) -> dict[str, Any]:
        """Extract all features for ML model."""
        clean_merchant = self.merchant_cleaner.clean(transaction.name)

        features = {
            # Numerical features
            "amount": transaction.amount,
            "amount_abs": abs(transaction.amount),
            "amount_log": np.log1p(abs(transaction.amount)),
            "is_income": int(transaction.amount > 0),
            "is_round_amount": int(abs(transaction.amount) % 10 == 0),
            "amount_magnitude": self._get_amount_magnitude(abs(transaction.amount)),
            # Temporal features
            "day_of_month": transaction.date.day,
            "day_of_week": transaction.date.weekday(),
            "month": transaction.date.month,
            "is_weekend": int(transaction.date.weekday() >= 5),
            "is_month_start": int(transaction.date.day <= 5),
            "is_month_end": int(transaction.date.day >= 25),
            "is_holiday_season": int(transaction.date.month in [11, 12, 1]),
            # Merchant features
            "merchant_clean": clean_merchant,
            "merchant_length": len(clean_merchant),
            "merchant_word_count": len(clean_merchant.split()) if clean_merchant else 0,
            # Transaction type indicators (from purpose field)
            "is_lastschrift": int("lastschrift" in transaction.purpose.lower()),
            "is_dauerauftrag": int("dauerauftrag" in transaction.purpose.lower()),
            "is_kartenzahlung": int("karte" in transaction.purpose.lower()),
            "is_online": int(any(x in transaction.purpose.lower() for x in ["online", "internet", "paypal", "amazon"])),
            "is_recurring": int(
                any(x in transaction.purpose.lower() for x in ["dauerauftrag", "standing order", "subscription"])
            ),
            # Merchant category indicators
            "is_supermarket": int(
                any(x in clean_merchant.lower() for x in ["edeka", "rewe", "aldi", "lidl", "kaufland", "netto"])
            ),
            "is_gas_station": int(
                any(x in clean_merchant.lower() for x in ["shell", "esso", "aral", "bp", "total", "tankstelle"])
            ),
            "is_restaurant": int(
                any(x in clean_merchant.lower() for x in ["mcdonald", "burger", "pizza", "restaurant", "cafe"])
            ),
            "is_transport": int(
                any(x in clean_merchant.lower() for x in ["deutsche bahn", "db ", "bvg", "uber", "taxi"])
            ),
            "is_tech": int(
                any(x in clean_merchant.lower() for x in ["amazon", "apple", "google", "microsoft", "netflix"])
            ),
            # Text for TF-IDF
            "text_combined": self.text_preprocessor.process(f"{transaction.name} {transaction.purpose}"),
            # Currency features
            "is_eur": int(transaction.currency == "EUR"),
            "currency": transaction.currency,
        }

        return features

    def _get_amount_magnitude(self, amount: float) -> int:
        """Categorize amount by magnitude."""
        if amount < 10:
            return 0  # small
        if amount < 50:
            return 1  # medium
        if amount < 200:
            return 2  # large
        if amount < 1000:
            return 3  # very large
        return 4  # huge

    def extract_batch_features(self, transactions: list[TransactionInput]) -> list[dict[str, Any]]:
        """Extract features for a batch of transactions."""
        return [self.extract_features(txn) for txn in transactions]

    def get_numerical_feature_names(self) -> list[str]:
        """Get names of numerical features."""
        return [
            "amount",
            "amount_abs",
            "amount_log",
            "is_income",
            "is_round_amount",
            "amount_magnitude",
            "day_of_month",
            "day_of_week",
            "month",
            "is_weekend",
            "is_month_start",
            "is_month_end",
            "is_holiday_season",
            "merchant_length",
            "merchant_word_count",
            "is_lastschrift",
            "is_dauerauftrag",
            "is_kartenzahlung",
            "is_online",
            "is_recurring",
            "is_supermarket",
            "is_gas_station",
            "is_restaurant",
            "is_transport",
            "is_tech",
            "is_eur",
        ]

    def get_categorical_feature_names(self) -> list[str]:
        """Get names of categorical features."""
        return ["merchant_clean", "currency"]

    def get_text_feature_names(self) -> list[str]:
        """Get names of text features."""
        return ["text_combined"]
