"""Which labels training, Merchant Rules, and calibration learn from.

Auto-accepts and bulk approves copy the model's own Prediction onto the
transaction. The calibration table and the training metrics use human labels
only, so the model never grades itself. Training and Merchant Rules also learn
from Trusted Auto-accepts: auto-accepts nobody corrected for a while, at a
lower weight.
"""

from collections import Counter
from datetime import date, timedelta

import pytest
from sqlalchemy.orm import Session

from fafycat.api.ml_insights import get_calibration_report
from fafycat.core.audit_trail import ReviewActor, record_review_event
from fafycat.core.config import MLConfig
from fafycat.core.database import CategoryORM, MerchantMappingORM, ReviewEventORM, TransactionORM
from fafycat.core.models import TransactionInput, TransactionPrediction
from fafycat.ml.categorizer import TransactionCategorizer
from fafycat.ml.ensemble_categorizer import EnsembleCategorizer
from fafycat.ml.feature_extractor import MerchantCleaner
from fafycat.ml.human_labels import AUTO_ACCEPT_LABEL_WEIGHT, TRUSTED_AUTO_ACCEPT_MIN_AGE, training_labels
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


def _age_review_events(db_session: Session) -> None:
    """Move every Review Event past the Trusted Auto-accept age, as if the import was weeks ago."""
    for event in db_session.query(ReviewEventORM):
        event.created_at = event.created_at - TRUSTED_AUTO_ACCEPT_MIN_AGE - timedelta(days=1)
    db_session.commit()


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
    def test_ensemble_trains_on_aged_auto_accepts_at_lower_weight(self, db_session, mixed_history):
        groceries, restaurants = mixed_history["groceries"], mixed_history["restaurants"]
        ensemble = EnsembleCategorizer(db_session, MLConfig())

        _, fresh_labels, fresh_weights = ensemble.prepare_training_data()
        _age_review_events(db_session)
        _, labels, weights = ensemble.prepare_training_data()

        # Fresh auto-accepts wait; aged ones train; bulk approves never do.
        assert Counter(fresh_labels.tolist()) == {groceries: 30, restaurants: 30}
        assert set(fresh_weights.tolist()) == {1.0}
        assert Counter(labels.tolist()) == {groceries: 30, restaurants: 70}
        assert Counter(weights.tolist()) == {1.0: 60, AUTO_ACCEPT_LABEL_WEIGHT: 40}

    def test_single_model_trains_on_aged_auto_accepts_at_lower_weight(self, db_session, mixed_history):
        _age_review_events(db_session)

        _, labels, weights = TransactionCategorizer(db_session, MLConfig()).prepare_training_data()

        assert Counter(labels.tolist()) == {mixed_history["groceries"]: 30, mixed_history["restaurants"]: 70}
        assert Counter(weights.tolist()) == {1.0: 60, AUTO_ACCEPT_LABEL_WEIGHT: 40}

    def test_ensemble_metrics_count_human_labels_only(self, db_session, mixed_history):
        _age_review_events(db_session)

        summary = EnsembleCategorizer(db_session, MLConfig(svd_n_components=10)).train()

        assert (summary["n_training_samples"], summary["n_evaluation_samples"]) == (100, 60)

    def test_models_train_on_trusted_auto_accepts_alone(self, db_session, cats):
        """Without a single Human Label there is nothing to grade on; training still completes."""
        groceries, restaurants = cats
        _auto_accept(db_session, {f"g{i:02d}": f"Corner Bakery {i}" for i in range(30)}, groceries)
        _auto_accept(db_session, {f"r{i:02d}": f"Trattoria Roma {i}" for i in range(30)}, restaurants)
        _age_review_events(db_session)
        config = MLConfig(svd_n_components=10)

        summary = EnsembleCategorizer(db_session, config).train()
        metrics = TransactionCategorizer(db_session, config).train()

        assert summary["n_evaluation_samples"] == 60
        assert 0.0 <= summary["oof_accuracy"] <= 1.0
        assert 0.0 <= metrics.accuracy <= 1.0

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

        _, labels, _ = EnsembleCategorizer(db_session, MLConfig()).prepare_training_data()

        assert Counter(labels.tolist())[groceries] == 31


class TestLegacyRows:
    """Rows labelled before the Audit Trail existed carry no Review Event."""

    def test_legacy_auto_accepts_train_at_lower_weight(self, db_session, cats):
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

        weights = {str(txn.id): weight for txn, weight in training_labels(db_session)}

        assert weights == {"old-auto": AUTO_ACCEPT_LABEL_WEIGHT, "old-fixed": 1.0, "old-review": 1.0, "old-import": 1.0}


class TestMerchantRules:
    def test_rebuild_forms_rules_from_aged_auto_accepts_but_not_bulk_approves(self, db_session, mixed_history):
        mapper = MerchantMapper(db_session)
        mapper.update_from_transactions()
        fresh = {m.merchant_pattern for m in db_session.query(MerchantMappingORM).all()}
        _age_review_events(db_session)
        mapper.update_from_transactions()
        aged = {m.merchant_pattern for m in db_session.query(MerchantMappingORM).all()}

        assert {"REWE MARKT 0", "TRATTORIA ROMA 0"} <= fresh
        assert "CORNER BAKERY 0" not in fresh
        assert "CORNER BAKERY 0" in aged
        assert "BULK SHOP 0" not in aged

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
        _age_review_events(db_session)  # Trusted Auto-accepts train, but never grade the model.

        top_band = get_calibration_report(db_session).bands[-1]

        assert (top_band.reviewed, top_band.kept) == (1, 0)


class TestTrainingReadiness:
    def test_auto_accepts_do_not_make_training_look_ready(self, test_client, db_session, cats):
        groceries, restaurants = cats
        db_session.query(TransactionORM).delete()
        for i in range(40):
            _label(db_session, f"rev{i:02d}", f"Trattoria Roma {i}", restaurants, ReviewActor.USER_REVIEW)
        db_session.commit()
        _auto_accept(db_session, {f"aut{i:02d}": f"Corner Bakery {i}" for i in range(20)}, groceries)

        status = test_client.get("/api/ml/status").json()
        import_page = test_client.get("/import").text

        assert (status["training_ready"], status["reviewed_transactions"]) == (False, 40)
        assert "Building training data" in import_page
