"""Name heuristics match whole words, not substrings.

Covers the merchant cleaner, partial Merchant Rule matching, the hand-written
merchant keyword features, and the category-type guess for new categories.
"""

from datetime import date

import pytest

from fafycat.core.config import AppConfig
from fafycat.core.database import CategoryORM, DatabaseManager, MerchantMappingORM, TransactionORM
from fafycat.core.models import TransactionInput
from fafycat.data.merchant_pattern import backfill_merchant_patterns
from fafycat.ml.feature_extractor import FeatureExtractor, MerchantCleaner
from fafycat.ml.merchant_mapper import PARTIAL_MATCH_PENALTY, MerchantRuleSet


class TestMerchantCleanerKeepsNames:
    @pytest.mark.parametrize(
        ("raw", "cleaned"),
        [
            # "de" and city names inside a name are part of the name.
            ("Cafe de Paris", "CAFE DE PARIS"),
            ("Frankfurt Airport", "FRANKFURT AIRPORT"),
            ("Deutsche Bahn Berlin Hbf", "DEUTSCHE BAHN BERLIN HBF"),
            ("Cafe de Berlin", "CAFE DE"),
            # Trailing location and country suffixes are still noise.
            ("REWE Markt Berlin DE", "REWE MARKT"),
            ("Amazon DE", "AMAZON"),
            ("Edeka Center Köln", "EDEKA CENTER"),
            ("EDEKA Markt Berlin 1234", "EDEKA MARKT"),
            ("REWE Markt 42", "REWE MARKT 42"),
            # A name that is only a city keeps it rather than becoming empty.
            ("Hamburg", "HAMBURG"),
        ],
    )
    def test_cleaning(self, raw, cleaned):
        assert MerchantCleaner().clean(raw) == cleaned


class TestPartialRuleMatching:
    def test_a_word_sharing_a_prefix_does_not_match(self):
        rules = MerchantRuleSet({"AMAZON": (1, 0.9)})

        assert rules.get_category("Amazing Thai Restaurant") is None

    def test_a_rule_whose_words_all_appear_matches_with_the_penalty(self):
        rules = MerchantRuleSet({"AMAZON": (1, 0.9)})

        match = rules.get_category("Amazon Marketplace")

        assert match is not None
        assert (match.merchant_pattern, match.category_id) == ("AMAZON", 1)
        assert match.confidence == pytest.approx(0.9 * PARTIAL_MATCH_PENALTY)

    @pytest.mark.parametrize("merchant", ["Amazon.com", "AMAZON-MARKETPLACE"])
    def test_punctuation_separates_words(self, merchant):
        rules = MerchantRuleSet({"AMAZON": (1, 0.9)})

        match = rules.get_category(merchant)

        assert match is not None
        assert match.merchant_pattern == "AMAZON"

    def test_a_multi_word_rule_needs_all_its_words(self):
        rules = MerchantRuleSet({"REWE MARKT": (1, 0.9)})

        assert rules.get_category("REWE City") is None

    def test_the_most_specific_rule_wins_whatever_the_insertion_order(self):
        for order in (["PAYPAL", "PAYPAL SPOTIFY"], ["PAYPAL SPOTIFY", "PAYPAL"]):
            categories = {"PAYPAL": (1, 0.9), "PAYPAL SPOTIFY": (2, 0.9)}
            rules = MerchantRuleSet({pattern: categories[pattern] for pattern in order})

            match = rules.get_category("PayPal *Spotify Premium")

            assert match is not None
            assert (match.merchant_pattern, match.category_id) == ("PAYPAL SPOTIFY", 2)


def _features(name: str) -> dict:
    txn = TransactionInput(date=date(2026, 3, 2), name=name, purpose="", amount=-20.0)
    return FeatureExtractor().extract_features(txn)


class TestMerchantKeywordFeatures:
    def test_a_keyword_inside_another_word_does_not_fire(self):
        features = _features("Subproject Totalcare")

        assert features["is_gas_station"] == 0

    def test_whole_word_keywords_still_fire(self):
        assert _features("TOTAL Tankstelle 123")["is_gas_station"] == 1
        assert _features("Deutsche Bahn Fernverkehr")["is_transport"] == 1
        assert _features("McDonald's 1234")["is_restaurant"] == 1
        assert _features("Bplus Consulting")["is_gas_station"] == 0


class TestCategoryTypeGuess:
    @pytest.fixture
    def manager(self, tmp_data_dir) -> DatabaseManager:
        config = AppConfig()
        config.database.url = f"sqlite:///{tmp_data_dir / 'types.db'}"
        manager = DatabaseManager(config)
        manager.create_tables()
        return manager

    def test_types_follow_whole_words(self, manager):
        names = {
            "paypal fees": "spending",
            "gifts": "spending",
            "miracle cure": "spending",
            "salary": "income",
            "tax_refund": "income",
            "dividends": "income",
            "emergency_fund": "saving",
            "savings": "saving",
            "etf": "saving",
        }

        manager.discover_categories_from_data(set(names))

        with manager.get_session() as session:
            types = {c.name: c.type for c in session.query(CategoryORM).all()}
        assert types == names


class TestStoredPatternsFollowTheCleaner:
    """A database cleaned by an older MerchantCleaner gets its patterns and rules recomputed once."""

    def test_old_patterns_and_rules_are_rebuilt_then_left_alone(self, db_session):
        cafe = CategoryORM(name="restaurants", type="spending", budget=0.0)
        db_session.add(cafe)
        db_session.flush()
        # What the old cleaner stored: "Cafe de Paris" cut down to "CAFE".
        db_session.add(
            TransactionORM(
                id="cafe",
                date=date(2026, 3, 1),
                name="Cafe de Paris",
                amount=-8.0,
                import_batch="old",
                merchant_pattern="CAFE",
                category_id=cafe.id,
                is_reviewed=True,
            )
        )
        db_session.add(MerchantMappingORM(merchant_pattern="CAFE", category_id=cafe.id, confidence=0.9))
        db_session.commit()

        assert backfill_merchant_patterns(db_session) == 1

        assert db_session.get(TransactionORM, "cafe").merchant_pattern == "CAFE DE PARIS"
        assert [m.merchant_pattern for m in db_session.query(MerchantMappingORM).all()] == ["CAFE DE PARIS"]
        # The cleaner version is recorded, so the next start does nothing.
        assert backfill_merchant_patterns(db_session) == 0
