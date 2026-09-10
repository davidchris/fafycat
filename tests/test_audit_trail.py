"""Audit Trail: Prediction Events and Review Events are recorded and rendered."""

import json
from datetime import UTC, date, datetime

from fafycat.core.audit_trail import ReviewActor, get_trail, record_review_event
from fafycat.core.database import (
    CategoryORM,
    MerchantMappingORM,
    ModelMetadataORM,
    PredictionEventORM,
    ReviewEventORM,
    TransactionORM,
)
from fafycat.core.models import PredictionDetail, ReviewPriority, TransactionInput, TransactionPrediction
from fafycat.ml.merchant_mapper import MerchantMapper
from fafycat.ml.prediction_pipeline import predict_unpredicted


class DetailedFakeCategorizer:
    """Categorizer double that fills in PredictionDetail like the ensemble does."""

    model_id = "abc123def456"

    def __init__(self, scores_by_name: dict[str, float], predicted_category_id: int):
        self.scores_by_name = scores_by_name
        self.predicted_category_id = predicted_category_id

    def predict_with_confidence(self, transactions: list[TransactionInput]) -> list[TransactionPrediction]:
        out = []
        for txn in transactions:
            score = self.scores_by_name[txn.name]
            out.append(
                TransactionPrediction(
                    transaction_id=txn.generate_id(),
                    predicted_category_id=self.predicted_category_id,
                    confidence_score=score,
                    feature_contributions={"amount": 0.4},
                    detail=PredictionDetail(
                        source="ensemble",
                        rule_pattern="REWE",
                        rule_category_id=self.predicted_category_id,
                        rule_confidence=0.85,
                        lgbm_probs={self.predicted_category_id: score, 99: 1 - score},
                        nb_probs={self.predicted_category_id: 0.5, 99: 0.5},
                        rule_probs={self.predicted_category_id: 0.85, 99: 0.15},
                        ensemble_probs={self.predicted_category_id: score, 99: 1 - score},
                        lgbm_weight=0.6,
                        nb_weight=0.2,
                        rule_weight=0.2,
                    ),
                )
            )
        return out


def _seed(db_session, name: str, txn_id: str, **overrides) -> TransactionORM:
    txn = TransactionORM(
        id=txn_id,
        date=date(2026, 8, 4),
        name=name,
        purpose="",
        amount=-12.5,
        currency="EUR",
        import_batch="b",
        imported_at=datetime.now(UTC),
        **overrides,
    )
    db_session.add(txn)
    db_session.flush()
    return txn


def _categories(db_session) -> tuple[CategoryORM, CategoryORM]:
    groceries = CategoryORM(name="groceries", type="spending", budget=0.0)
    eating = CategoryORM(name="eating out", type="spending", budget=0.0)
    db_session.add_all([groceries, eating])
    db_session.flush()
    return groceries, eating


class TestPipelineWritesEvents:
    def test_one_prediction_event_per_transaction_with_full_detail(self, db_session):
        groceries, _ = _categories(db_session)
        _seed(db_session, "REWE", "a" * 16)
        _seed(db_session, "Uniqlo", "b" * 16)
        db_session.commit()

        predict_unpredicted(
            db_session, DetailedFakeCategorizer({"REWE": 0.97, "Uniqlo": 0.33}, groceries.id), threshold=0.9
        )

        events = {e.transaction_id: e for e in db_session.query(PredictionEventORM).all()}
        assert set(events) == {"a" * 16, "b" * 16}
        rewe = events["a" * 16]
        assert rewe.trigger == "batch_unpredicted"
        assert rewe.model_id == "abc123def456"
        assert rewe.decision == ReviewPriority.AUTO_ACCEPTED.value
        assert rewe.source == "ensemble"
        assert rewe.rule_pattern == "REWE" and rewe.rule_confidence == 0.85
        assert rewe.lgbm_weight == 0.6 and rewe.nb_weight == 0.2 and rewe.rule_weight == 0.2
        assert '"99"' in rewe.lgbm_probs and rewe.nb_probs and rewe.ensemble_probs
        assert json.loads(rewe.rule_probs) == {str(groceries.id): 0.85, "99": 0.15}
        assert events["b" * 16].decision == ReviewPriority.STANDARD.value

    def test_auto_accept_writes_a_review_event_but_needs_review_does_not(self, db_session):
        groceries, _ = _categories(db_session)
        _seed(db_session, "REWE", "a" * 16)
        _seed(db_session, "Uniqlo", "b" * 16)
        db_session.commit()

        predict_unpredicted(
            db_session, DetailedFakeCategorizer({"REWE": 0.97, "Uniqlo": 0.33}, groceries.id), threshold=0.9
        )

        reviews = db_session.query(ReviewEventORM).all()
        assert [(r.transaction_id, r.actor, r.to_category_id) for r in reviews] == [
            ("a" * 16, ReviewActor.AUTO_ACCEPT.value, groceries.id)
        ]


class TestHumanActionsWriteEvents:
    def test_user_review_records_from_and_to(self, test_client, db_session):
        groceries, eating = _categories(db_session)
        _seed(db_session, "REWE", "a" * 16, predicted_category_id=eating.id, confidence_score=0.6)
        db_session.commit()

        resp = test_client.put(f"/api/transactions/{'a' * 16}/categorize-htmx", data={"actual_category": "groceries"})
        assert resp.status_code == 200

        event = db_session.query(ReviewEventORM).one()
        assert event.actor == ReviewActor.USER_REVIEW.value
        assert event.from_category_id is None
        assert event.to_category_id == groceries.id
        assert event.predicted_category_id == eating.id
        assert event.confidence_score == 0.6

    def test_bulk_approve_records_one_event_per_transaction(self, test_client, db_session):
        groceries, _ = _categories(db_session)
        _seed(
            db_session,
            "REWE",
            "a" * 16,
            predicted_category_id=groceries.id,
            confidence_score=0.96,
            review_priority=ReviewPriority.QUALITY_CHECK,
        )
        db_session.commit()

        resp = test_client.post("/api/transactions/bulk-approve")
        assert resp.json()["approved"] == 1

        event = db_session.query(ReviewEventORM).one()
        assert event.actor == ReviewActor.BULK_APPROVE.value
        assert event.to_category_id == groceries.id


class TestTrailAssembly:
    def test_trail_merges_streams_newest_first_and_resolves_names(self, db_session):
        groceries, eating = _categories(db_session)
        txn = _seed(db_session, "REWE", "a" * 16)
        db_session.commit()
        predict_unpredicted(db_session, DetailedFakeCategorizer({"REWE": 0.6}, eating.id), threshold=0.9)
        record_review_event(
            db_session, txn, actor=ReviewActor.USER_REVIEW, from_category_id=None, to_category_id=groceries.id
        )
        db_session.commit()

        trail = get_trail(db_session, "a" * 16)

        assert trail is not None
        assert [ev.kind for ev in trail.events] == ["review", "prediction"]
        prediction = trail.events[1]
        assert prediction.final_category == "eating out"
        assert prediction.rule_category == "eating out"
        assert prediction.rule_weight == 0.2
        assert [r.category for r in prediction.rule_top][0] == "eating out"
        assert [r.category for r in prediction.lgbm_top][0] == "eating out"
        assert trail.events[0].to_category == "groceries"

    def test_unknown_transaction_returns_none(self, db_session):
        assert get_trail(db_session, "nope") is None


class TestPages:
    def test_trail_page_renders_components_and_decision(self, test_client, db_session):
        groceries, _ = _categories(db_session)
        _seed(db_session, "REWE", "a" * 16)
        db_session.commit()
        predict_unpredicted(db_session, DetailedFakeCategorizer({"REWE": 0.97}, groceries.id), threshold=0.9)

        resp = test_client.get(f"/transactions/{'a' * 16}/trail")

        assert resp.status_code == 200
        for needle in (
            "Audit trail",
            "LightGBM",
            "Naive Bayes",
            "Ensemble",
            "Merchant rule (weight 0.20)",
            "proposed groceries at 85.0%, voting with weight 0.20",
            "auto-accepted",
            "abc123def456",
        ):
            assert needle in resp.text, needle
        assert "applied" not in resp.text

    def test_trail_page_without_events_explains_why(self, test_client, db_session):
        _categories(db_session)
        _seed(db_session, "REWE", "a" * 16)
        db_session.commit()

        resp = test_client.get(f"/transactions/{'a' * 16}/trail")

        assert resp.status_code == 200
        assert "No trail recorded" in resp.text

    def test_trail_page_404_for_unknown_transaction(self, test_client):
        assert test_client.get("/transactions/unknown/trail").status_code == 404

    def test_review_table_links_to_trail(self, test_client, db_session):
        groceries, _ = _categories(db_session)
        _seed(db_session, "REWE", "a" * 16, predicted_category_id=groceries.id, confidence_score=0.5)
        db_session.commit()

        resp = test_client.get("/api/transactions/table?status=all")

        assert f'href="/transactions/{"a" * 16}/trail"' in resp.text

    def test_rules_page_lists_rules(self, test_client, db_session):
        groceries, _ = _categories(db_session)
        db_session.add(
            MerchantMappingORM(
                merchant_pattern="VISA PAYPAL SPOTIFY", category_id=groceries.id, confidence=0.98, occurrence_count=21
            )
        )
        db_session.commit()

        resp = test_client.get("/rules")

        assert resp.status_code == 200
        assert "Merchant rules (1)" in resp.text
        assert "VISA PAYPAL SPOTIFY" in resp.text and "98%" in resp.text
        assert "No model is trained yet" in resp.text

    def test_rules_page_names_the_learned_rule_weight(self, test_client, db_session):
        db_session.add(
            ModelMetadataORM(
                model_version="1.0-ensemble",
                accuracy=0.83,
                feature_importance=json.dumps({"ensemble_weights": {"lgbm": 0.5, "nb": 0.3, "rule": 0.2}}),
                is_active=True,
            )
        )
        db_session.commit()

        resp = test_client.get("/rules")

        assert "that weight is 20%" in resp.text
        assert "50% for LightGBM" in resp.text and "30% for Naive Bayes" in resp.text


class TestMerchantRuleRebuild:
    def test_rebuild_groups_by_cleaned_pattern_and_drops_stale_rules(self, db_session):
        groceries, eating = _categories(db_session)
        # Stale rule from the old cleaner that collapsed every PayPal merchant.
        db_session.add(MerchantMappingORM(merchant_pattern="VISA PAYPAL", category_id=eating.id, confidence=0.98))
        for i in range(3):
            _seed(db_session, "VISA PayPal *Spotify", f"s{i:015d}", category_id=groceries.id, is_reviewed=True)
        for i in range(3):
            _seed(db_session, "VISA PayPal *BVG-App", f"b{i:015d}", category_id=eating.id, is_reviewed=True)
        # Two reviews only: below the minimum, no rule.
        for i in range(2):
            _seed(db_session, "Uniqlo", f"u{i:015d}", category_id=groceries.id, is_reviewed=True)
        db_session.commit()

        MerchantMapper(db_session).update_from_transactions(min_occurrences=3)

        rules = {
            m.merchant_pattern: (m.category_id, m.confidence, m.occurrence_count)
            for m in db_session.query(MerchantMappingORM)
        }
        assert rules == {
            "VISA PAYPAL SPOTIFY": (groceries.id, 0.98, 3),
            "VISA PAYPAL BVG-APP": (eating.id, 0.98, 3),
        }

    def test_mixed_categories_below_share_form_no_rule(self, db_session):
        groceries, eating = _categories(db_session)
        for i in range(3):
            _seed(db_session, "Kiosk", f"k{i:015d}", category_id=groceries.id, is_reviewed=True)
        for i in range(2):
            _seed(db_session, "Kiosk", f"e{i:015d}", category_id=eating.id, is_reviewed=True)
        db_session.commit()

        MerchantMapper(db_session).update_from_transactions(min_occurrences=3)

        assert db_session.query(MerchantMappingORM).count() == 0
