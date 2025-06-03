"""Tests for feature extraction functionality."""

from datetime import date

import pytest

from fafycat.core.models import TransactionInput
from fafycat.ml.feature_extractor import FeatureExtractor, MerchantCleaner, TextPreprocessor


class TestMerchantCleaner:
    """Test merchant name cleaning functionality."""

    def test_basic_cleaning(self):
        """Test basic merchant name cleaning."""
        cleaner = MerchantCleaner()

        test_cases = [
            ("EDEKA Schmitt, Berlin", "EDEKA SCHMITT,"),
            ("REWE//Berlin/DE 2024.01.01", "REWE"),
            ("Amazon *Marketplace", "AMAZON"),
            ("McDonald's München", "MCDONALD'S"),
            ("Shell Tankstelle//Hamburg", "SHELL TANKSTELLE"),
        ]

        for input_text, expected in test_cases:
            result = cleaner.clean(input_text)
            assert result == expected, f"Expected '{expected}', got '{result}' for input '{input_text}'"

    def test_date_removal(self):
        """Test removal of dates from merchant names."""
        cleaner = MerchantCleaner()

        assert cleaner.clean("EDEKA 2024.01.15 München") == "EDEKA"
        assert cleaner.clean("REWE Markt 2023.12.31") == "REWE MARKT"

    def test_empty_input(self):
        """Test handling of empty input."""
        cleaner = MerchantCleaner()

        assert cleaner.clean("") == ""
        assert cleaner.clean("   ") == ""
        assert cleaner.clean(None) == ""


class TestTextPreprocessor:
    """Test text preprocessing functionality."""

    def test_basic_processing(self):
        """Test basic text processing."""
        processor = TextPreprocessor()

        test_cases = [
            ("Kartenzahlung Online-Kauf", "kartenzahlung online kauf"),
            ("Lastschrift mit Referenz", "lastschrift referenz"),
            ("AMAZON MARKETPLACE", "amazon marketplace"),
        ]

        for input_text, expected in test_cases:
            result = processor.process(input_text)
            assert result == expected, f"Expected '{expected}', got '{result}'"

    def test_stopword_removal(self):
        """Test removal of German stopwords."""
        processor = TextPreprocessor()

        result = processor.process("Das ist eine Lastschrift und Kartenzahlung")
        # Note: "ist" has 3 characters so it won't be filtered out by length check
        assert "das" not in result
        assert "eine" not in result
        assert "und" not in result
        assert "lastschrift" in result
        assert "kartenzahlung" in result


class TestFeatureExtractor:
    """Test feature extraction functionality."""

    def test_numerical_features(self):
        """Test extraction of numerical features."""
        extractor = FeatureExtractor()

        transaction = TransactionInput(
            date=date(2024, 1, 15), name="EDEKA Markt 1234", purpose="Lastschrift", amount=-45.67
        )

        features = extractor.extract_features(transaction)

        # Check numerical features
        assert features["amount"] == -45.67
        assert features["amount_abs"] == 45.67
        assert features["is_income"] == 0
        assert features["day_of_month"] == 15
        assert features["day_of_week"] == 0  # Monday
        assert features["month"] == 1
        assert features["is_weekend"] == 0
        assert features["is_month_start"] == 0
        assert features["is_month_end"] == 0

    def test_temporal_features(self):
        """Test extraction of temporal features."""
        extractor = FeatureExtractor()

        # Weekend transaction
        transaction = TransactionInput(
            date=date(2024, 1, 28),  # Sunday
            name="Restaurant",
            purpose="Kartenzahlung",
            amount=-25.50,
        )

        features = extractor.extract_features(transaction)

        assert features["day_of_week"] == 6  # Sunday
        assert features["is_weekend"] == 1
        assert features["is_month_end"] == 1  # 28th is >= 25

    def test_merchant_features(self):
        """Test merchant-specific features."""
        extractor = FeatureExtractor()

        transaction = TransactionInput(
            date=date(2024, 1, 15), name="EDEKA Markt Berlin 1234", purpose="Lastschrift", amount=-35.90
        )

        features = extractor.extract_features(transaction)

        assert features["is_supermarket"] == 1
        assert features["is_lastschrift"] == 1
        assert features["merchant_clean"] == "EDEKA MARKT"
        assert features["merchant_length"] > 0
        assert features["merchant_word_count"] == 2

    def test_transaction_type_features(self):
        """Test transaction type detection."""
        extractor = FeatureExtractor()

        # Online transaction
        transaction = TransactionInput(
            date=date(2024, 1, 15), name="Amazon Marketplace", purpose="Online-Kauf PayPal", amount=-89.99
        )

        features = extractor.extract_features(transaction)

        assert features["is_online"] == 1
        assert features["is_tech"] == 1

    def test_amount_magnitude(self):
        """Test amount magnitude categorization."""
        extractor = FeatureExtractor()

        test_cases = [
            (5.50, 0),  # small
            (25.00, 1),  # medium
            (150.00, 2),  # large
            (750.00, 3),  # very large
            (1500.00, 4),  # huge
        ]

        for amount, expected_magnitude in test_cases:
            transaction = TransactionInput(date=date(2024, 1, 15), name="Test", purpose="Test", amount=-amount)

            features = extractor.extract_features(transaction)
            assert features["amount_magnitude"] == expected_magnitude

    def test_batch_processing(self):
        """Test batch feature extraction."""
        extractor = FeatureExtractor()

        transactions = [
            TransactionInput(date=date(2024, 1, 15), name="EDEKA", purpose="Lastschrift", amount=-45.67),
            TransactionInput(date=date(2024, 1, 16), name="McDonald's", purpose="Kartenzahlung", amount=-12.50),
        ]

        features_list = extractor.extract_batch_features(transactions)

        assert len(features_list) == 2
        assert features_list[0]["is_supermarket"] == 1
        assert features_list[1]["is_restaurant"] == 1


if __name__ == "__main__":
    pytest.main([__file__])
