"""Tests for the training-recency and calibration read models."""

from datetime import UTC, date, datetime, timedelta

import pytest
from fafycat.api.ml_insights import get_calibration_report, get_training_recency
from fafycat.core.database import (
    AppSettingsORM,
    CategoryORM,
    ModelMetadataORM,
    ReviewEventORM,
    TransactionORM,
)


@pytest.fixture
def categories(db_session) -> tuple[int, int]:
    """Two categories to predict and correct between."""
    groceries = CategoryORM(name="groceries", type="spending")
    restaurants = CategoryORM(name="restaurants", type="spending")
    db_session.add_all([groceries, restaurants])
    db_session.commit()
    return int(groceries.id), int(restaurants.id)


def _add_review_event(db_session, actor: str, created_at: datetime, to_category_id: int) -> None:
    db_session.add(
        ReviewEventORM(
            transaction_id="t" + str(abs(hash((actor, created_at))))[:8],
            created_at=created_at,
            actor=actor,
            to_category_id=to_category_id,
        )
    )


def _add_transaction(
    db_session,
    txn_id: str,
    *,
    confidence: float | None,
    category_id: int | None,
    predicted_category_id: int | None,
    is_reviewed: bool = True,
    review_priority: str = "standard",
) -> None:
    db_session.add(
        TransactionORM(
            id=txn_id,
            date=date(2025, 1, 1),
            name=f"Merchant {txn_id}",
            amount=-10.0,
            import_batch="test",
            confidence_score=confidence,
            category_id=category_id,
            predicted_category_id=predicted_category_id,
            is_reviewed=is_reviewed,
            review_priority=review_priority,
        )
    )


class TestTrainingRecency:
    """get_training_recency reports staleness of the active model."""

    def test_never_trained_counts_every_labelling_event(self, db_session, categories):
        groceries, _ = categories
        for i in range(3):
            _add_review_event(db_session, "user_review", datetime(2025, 1, i + 1), groceries)
        db_session.commit()

        recency = get_training_recency(db_session)

        assert recency.last_trained_at is None
        assert recency.reviews_since_training == 3

    def test_counts_only_events_after_training(self, db_session, categories):
        groceries, _ = categories
        trained_at = datetime(2025, 6, 1, 12, 0)
        db_session.add(ModelMetadataORM(model_version="v1", training_date=trained_at, is_active=True))
        _add_review_event(db_session, "user_review", trained_at - timedelta(days=1), groceries)
        _add_review_event(db_session, "user_review", trained_at + timedelta(days=1), groceries)
        _add_review_event(db_session, "bulk_approve", trained_at + timedelta(days=2), groceries)
        db_session.commit()

        recency = get_training_recency(db_session)

        assert recency.last_trained_at == trained_at.replace(tzinfo=UTC)
        assert recency.reviews_since_training == 2

    def test_auto_accepts_are_not_training_signal(self, db_session, categories):
        groceries, _ = categories
        _add_review_event(db_session, "auto_accept", datetime(2025, 1, 1), groceries)
        _add_review_event(db_session, "import_label", datetime(2025, 1, 2), groceries)
        _add_review_event(db_session, "propagation", datetime(2025, 1, 3), groceries)
        db_session.commit()

        assert get_training_recency(db_session).reviews_since_training == 2

    def test_ignores_superseded_inactive_models(self, db_session, categories):
        groceries, _ = categories
        db_session.add(ModelMetadataORM(model_version="old", training_date=datetime(2025, 1, 1), is_active=False))
        db_session.add(ModelMetadataORM(model_version="new", training_date=datetime(2025, 6, 1), is_active=True))
        _add_review_event(db_session, "user_review", datetime(2025, 3, 1), groceries)
        db_session.commit()

        recency = get_training_recency(db_session)

        assert recency.last_trained_at == datetime(2025, 6, 1, tzinfo=UTC)
        assert recency.reviews_since_training == 0

    def test_to_dict_renders_iso_timestamp(self, db_session):
        db_session.add(ModelMetadataORM(model_version="v1", training_date=datetime(2025, 6, 1), is_active=True))
        db_session.commit()

        payload = get_training_recency(db_session).to_dict()

        assert payload["last_trained_at"] == "2025-06-01T00:00:00+00:00"
        assert payload["reviews_since_training"] == 0


class TestCalibrationReport:
    """get_calibration_report splits review outcomes by confidence band."""

    def test_bands_cover_the_configured_edges(self, db_session):
        report = get_calibration_report(db_session)

        assert [band.label for band in report.bands] == [
            "0.00-0.50",
            "0.50-0.80",
            "0.80-0.90",
            "0.90-0.95",
            "0.95-1.00",
        ]
        assert all(band.reviewed == 0 and band.agreement_rate is None for band in report.bands)

    def test_counts_kept_and_overridden_per_band(self, db_session, categories):
        groceries, restaurants = categories
        # Band 0.00-0.50: one kept, one overridden.
        _add_transaction(db_session, "a1", confidence=0.10, category_id=groceries, predicted_category_id=groceries)
        _add_transaction(db_session, "a2", confidence=0.49, category_id=restaurants, predicted_category_id=groceries)
        # Band 0.90-0.95: lower edge inclusive, upper edge exclusive.
        _add_transaction(db_session, "b1", confidence=0.90, category_id=groceries, predicted_category_id=groceries)
        _add_transaction(db_session, "b2", confidence=0.949, category_id=groceries, predicted_category_id=groceries)
        # Band 0.95-1.00: upper edge inclusive.
        _add_transaction(db_session, "c1", confidence=0.95, category_id=groceries, predicted_category_id=groceries)
        _add_transaction(db_session, "c2", confidence=1.0, category_id=restaurants, predicted_category_id=groceries)
        db_session.commit()

        bands = {band.label: band for band in get_calibration_report(db_session).bands}

        assert (bands["0.00-0.50"].reviewed, bands["0.00-0.50"].kept) == (2, 1)
        assert bands["0.00-0.50"].overridden == 1
        assert bands["0.00-0.50"].agreement_rate == 0.5
        assert (bands["0.90-0.95"].reviewed, bands["0.90-0.95"].kept) == (2, 2)
        assert bands["0.90-0.95"].agreement_rate == 1.0
        assert (bands["0.95-1.00"].reviewed, bands["0.95-1.00"].kept) == (2, 1)
        assert bands["0.50-0.80"].reviewed == 0

    def test_skips_unreviewed_and_unpredicted_transactions(self, db_session, categories):
        groceries, _ = categories
        _add_transaction(
            db_session, "u1", confidence=0.3, category_id=None, predicted_category_id=groceries, is_reviewed=False
        )
        _add_transaction(db_session, "u2", confidence=0.3, category_id=groceries, predicted_category_id=None)
        _add_transaction(db_session, "u3", confidence=None, category_id=groceries, predicted_category_id=groceries)
        db_session.commit()

        assert sum(band.reviewed for band in get_calibration_report(db_session).bands) == 0

    def test_skips_rows_flagged_reviewed_but_left_uncategorised(self, db_session, categories):
        """A missing category is stale data, not the reviewer disagreeing."""
        groceries, _ = categories
        _add_transaction(db_session, "n1", confidence=0.97, category_id=None, predicted_category_id=groceries)
        _add_transaction(db_session, "n2", confidence=0.97, category_id=groceries, predicted_category_id=groceries)
        db_session.commit()

        top_band = get_calibration_report(db_session).bands[-1]

        assert (top_band.reviewed, top_band.kept, top_band.overridden) == (1, 1, 0)
        assert top_band.agreement_rate == 1.0

    def test_counts_auto_accepted_transactions_the_user_corrected(self, db_session, categories):
        groceries, restaurants = categories
        _add_transaction(
            db_session,
            "x1",
            confidence=0.97,
            category_id=restaurants,
            predicted_category_id=groceries,
            review_priority="auto_accepted",
        )
        _add_transaction(
            db_session,
            "x2",
            confidence=0.97,
            category_id=groceries,
            predicted_category_id=groceries,
            review_priority="auto_accepted",
        )
        _add_transaction(
            db_session,
            "x3",
            confidence=0.30,
            category_id=restaurants,
            predicted_category_id=groceries,
            review_priority="standard",
        )
        db_session.commit()

        assert get_calibration_report(db_session).auto_accepted_overridden == 1

    def test_reports_the_threshold_in_force(self, db_session):
        db_session.add(AppSettingsORM(key="auto_approve_threshold", value="0.85"))
        db_session.commit()

        assert get_calibration_report(db_session).threshold == 0.85

    def test_to_dict_shape(self, db_session, categories):
        groceries, _ = categories
        _add_transaction(db_session, "d1", confidence=0.99, category_id=groceries, predicted_category_id=groceries)
        db_session.commit()

        payload = get_calibration_report(db_session).to_dict()

        assert len(payload["bands"]) == 5
        assert payload["bands"][-1] == {
            "lower": 0.95,
            "upper": 1.0,
            "label": "0.95-1.00",
            "reviewed": 1,
            "kept": 1,
            "overridden": 0,
            "agreement_rate": 1.0,
        }
        assert payload["auto_accepted_overridden"] == 0
        assert "caveat" in payload


class TestMLStatusEndpoint:
    """/api/ml/status carries the training-recency fields."""

    def test_reports_never_trained(self, test_client, db_session):
        db_session.query(TransactionORM).delete()
        db_session.commit()

        status = test_client.get("/api/ml/status").json()

        assert status["last_trained_at"] is None
        assert status["reviews_since_training"] == 0

    def test_counts_reviews_recorded_after_training(self, test_client, db_session, categories):
        groceries, _ = categories
        trained_at = datetime(2025, 6, 1, 12, 0)
        db_session.add(ModelMetadataORM(model_version="v1", training_date=trained_at, is_active=True))
        _add_review_event(db_session, "user_review", trained_at - timedelta(days=1), groceries)
        _add_review_event(db_session, "user_review", trained_at + timedelta(days=1), groceries)
        db_session.commit()

        status = test_client.get("/api/ml/status").json()

        assert status["last_trained_at"] == "2025-06-01T12:00:00+00:00"
        assert status["reviews_since_training"] == 1


class TestCalibrationEndpoint:
    """/api/ml/calibration returns the report as JSON."""

    def test_json_shape(self, test_client, db_session, categories):
        groceries, restaurants = categories
        _add_transaction(db_session, "e1", confidence=0.99, category_id=groceries, predicted_category_id=groceries)
        _add_transaction(db_session, "e2", confidence=0.20, category_id=restaurants, predicted_category_id=groceries)
        db_session.commit()

        payload = test_client.get("/api/ml/calibration").json()

        assert payload["threshold"] == pytest.approx(0.9)
        assert payload["auto_accepted_overridden"] == 0
        assert [band["label"] for band in payload["bands"]] == [
            "0.00-0.50",
            "0.50-0.80",
            "0.80-0.90",
            "0.90-0.95",
            "0.95-1.00",
        ]
        by_label = {band["label"]: band for band in payload["bands"]}
        assert by_label["0.95-1.00"]["kept"] == 1
        assert by_label["0.00-0.50"]["overridden"] == 1
        assert by_label["0.00-0.50"]["agreement_rate"] == 0.0
        assert by_label["0.50-0.80"]["agreement_rate"] is None
