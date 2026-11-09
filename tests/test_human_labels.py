"""Training, Merchant Rules, and calibration learn from human labels only.

Auto-accepts and bulk approves copy the model's own Prediction onto the
transaction. Feeding them back into training, rules, or the calibration table
would let the model confirm itself.
"""

from collections import Counter
from datetime import date

import pytest
from sqlalchemy.orm import Session

from fafycat.api.ml_insights import get_calibration_report
from fafycat.core.audit_trail import ReviewActor, record_review_event
from fafycat.core.config import MLConfig
from fafycat.core.database import CategoryORM, MerchantMappingORM, TransactionORM
from fafycat.core.models import TransactionInput, TransactionPrediction
from fafycat.ml.categorizer import TransactionCategorizer
from fafycat.ml.ensemble_categorizer import EnsembleCategorizer
from fafycat.ml.feature_extractor import MerchantCleaner
from fafycat.ml.merchant_mapper import MerchantMapper, refresh_rule_for_pattern
from fafycat.ml.prediction_pipeline import predict_unpredicted


class ConfidentCategorizer:
    """Predicts one category at a fixed confidence, so every prediction auto-accepts."""

    model_id = "confident"

    def __init__(self, category_id: int, confidence: float = 0.99):
        self.category_id = category_id
        self.confidence = confidence

    def predict_with_confidence(self, transactions: list[TransactionInput]) -> list[TransactionPrediction]:
        return [
            TransactionPrediction(
                transaction_id=txn.generate_id(),
                predicted_category_id=self.category_id,
                confidence_score=self.confidence,
                feature_contributions={},
            )
            for txn in transactions
        ]


@pytest.fixture
def cats(db_session: Session) -> tuple[int, int]:
    groceries = CategoryORM(name="groceries", type="spending", budget=0.0)
    restaurants = CategoryORM(name="restaurants", type="spending", budget=0.0)
    db_session.add_all([groceries, restaurants])
    db_session.commit()
    return int(groceries.id), int(restaurants.id)


def _txn(db_session: Session, txn_id: str, name: str, **fields) -> TransactionORM:
    txn = TransactionORM(
        id=txn_id,
        date=date(2026, 3, 1),
        value_date=date(2026, 3, 1),
        name=name,
        purpose="",
        amount=-12.0,
        currency="EUR",
        import_batch="test",
        merchant_pattern=MerchantCleaner().clean(name),
        **fields,
    )
    db_session.add(txn)
    db_session.flush()
    return txn


def _label(db_session: Session, txn_id: str, name: str, category_id: int, actor: ReviewActor) -> TransactionORM:
    """Store a transaction whose category was set by ``actor``, with its Review Event."""
    txn = _txn(db_session, txn_id, name, predicted_category_id=category_id, confidence_score=0.6)
    record_review_event(db_session, txn, actor=actor, from_category_id=None, to_category_id=category_id)
    txn.category_id = category_id
    txn.is_reviewed = True
    return txn


def _auto_accept(db_session: Session, names: dict[str, str], category_id: int) -> None:
    """Import unlabelled transactions and let the real Prediction Pipeline auto-accept them."""
    for txn_id, name in names.items():
        _txn(db_session, txn_id, name)
    db_session.commit()
    summary, _ = predict_unpredicted(db_session, ConfidentCategorizer(category_id), threshold=0.9)
    assert summary.auto_accepted == len(names)


@pytest.fixture
def mixed_history(db_session: Session, cats: tuple[int, int]) -> dict[str, int]:
    """30 import labels, 25 reviews, 5 propagations, and 40 auto-accepts plus 10 bulk approves."""
    groceries, restaurants = cats
    for i in range(30):
        _label(db_session, f"imp{i:02d}", f"REWE Markt {i}", groceries, ReviewActor.IMPORT_LABEL)
    for i in range(25):
        _label(db_session, f"rev{i:02d}", f"Trattoria Roma {i}", restaurants, ReviewActor.USER_REVIEW)
    for i in range(5):
        _label(db_session, f"pro{i:02d}", f"Trattoria Roma {i}", restaurants, ReviewActor.PROPAGATION)
    for i in range(10):
        _label(db_session, f"blk{i:02d}", f"Bulk Shop {i}", groceries, ReviewActor.BULK_APPROVE)
    db_session.commit()
    # The auto-accepts land on restaurants: if they leak into training, the class balance shows it.
    _auto_accept(db_session, {f"aut{i:02d}": f"Corner Bakery {i}" for i in range(40)}, restaurants)
    return {"groceries": groceries, "restaurants": restaurants}


class TestTrainingData:
    def test_ensemble_trains_on_human_labels_only(self, db_session, mixed_history):
        _, labels = EnsembleCategorizer(db_session, MLConfig()).prepare_training_data()

        assert Counter(labels.tolist()) == {mixed_history["groceries"]: 30, mixed_history["restaurants"]: 30}

    def test_single_model_trains_on_human_labels_only(self, db_session, mixed_history):
        _, labels = TransactionCategorizer(db_session, MLConfig()).prepare_training_data()

        assert Counter(labels.tolist()) == {mixed_history["groceries"]: 30, mixed_history["restaurants"]: 30}

    def test_a_reviewer_correcting_an_auto_accept_makes_it_a_human_label(self, db_session, mixed_history):
        groceries = mixed_history["groceries"]
        corrected = db_session.get(TransactionORM, "aut00")
        record_review_event(
            db_session,
            corrected,
            actor=ReviewActor.USER_REVIEW,
            from_category_id=int(corrected.category_id),
            to_category_id=groceries,
        )
        corrected.category_id = groceries
        db_session.commit()

        _, labels = EnsembleCategorizer(db_session, MLConfig()).prepare_training_data()

        assert Counter(labels.tolist())[groceries] == 31


class TestLegacyRows:
    """Rows labelled before the Audit Trail existed carry no Review Event."""

    def test_legacy_auto_accepts_are_excluded_but_legacy_corrections_kept(self, db_session, cats):
        groceries, restaurants = cats
        # Legacy auto-accept: category copied from the prediction.
        _txn(
            db_session,
            "old-auto",
            "Old Auto",
            category_id=groceries,
            predicted_category_id=groceries,
            is_reviewed=True,
            review_priority="auto_accepted",
        )
        # Legacy auto-accept a reviewer later corrected: category differs from the prediction.
        _txn(
            db_session,
            "old-fixed",
            "Old Fixed",
            category_id=restaurants,
            predicted_category_id=groceries,
            is_reviewed=True,
            review_priority="auto_accepted",
        )
        # Legacy review and legacy labelled import.
        _txn(
            db_session, "old-review", "Old Review", category_id=groceries, is_reviewed=True, review_priority="standard"
        )
        _txn(db_session, "old-import", "Old Import", category_id=groceries, is_reviewed=True)
        db_session.commit()

        rows = MerchantMapper(db_session).reviewed_transactions()

        assert sorted(name for name, _, _ in rows) == ["Old Fixed", "Old Import", "Old Review"]


class TestMerchantRules:
    def test_rebuild_forms_no_rule_from_auto_accepts(self, db_session, mixed_history):
        MerchantMapper(db_session).update_from_transactions()

        patterns = {m.merchant_pattern for m in db_session.query(MerchantMappingORM).all()}
        assert "CORNER BAKERY 0" not in patterns
        assert "BULK SHOP 0" not in patterns
        assert "REWE MARKT 0" in patterns
        assert "TRATTORIA ROMA 0" in patterns

    def test_refresh_after_review_ignores_auto_accepted_siblings(self, db_session, cats):
        groceries, restaurants = cats
        # Three auto-accepted siblings say groceries, the one human review says restaurants.
        _auto_accept(db_session, {f"sib{i}": "Corner Bakery" for i in range(3)}, groceries)
        _label(db_session, "human", "Corner Bakery", restaurants, ReviewActor.USER_REVIEW)
        db_session.commit()

        assert refresh_rule_for_pattern(db_session, "CORNER BAKERY") is True

        rule = db_session.query(MerchantMappingORM).filter_by(merchant_pattern="CORNER BAKERY").one()
        assert (rule.category_id, rule.occurrence_count) == (restaurants, 1)


class TestCalibration:
    def test_auto_accepted_rows_are_not_counted_as_agreement(self, db_session, cats):
        groceries, restaurants = cats
        _auto_accept(db_session, {f"aa{i}": f"Shop {i}" for i in range(5)}, groceries)
        # One human review at the same confidence that overrode the prediction.
        human = _txn(db_session, "hum", "Human Shop", predicted_category_id=groceries, confidence_score=0.99)
        record_review_event(
            db_session, human, actor=ReviewActor.USER_REVIEW, from_category_id=None, to_category_id=restaurants
        )
        human.category_id = restaurants
        human.is_reviewed = True
        db_session.commit()

        top_band = get_calibration_report(db_session).bands[-1]

        assert (top_band.reviewed, top_band.kept) == (1, 0)
