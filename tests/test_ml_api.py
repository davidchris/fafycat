"""Tests for the ML API endpoints, run against a real, trained EnsembleCategorizer."""

from datetime import date, timedelta

import pytest

from fafycat.api.ml import get_categorizer
from fafycat.core.config import MLConfig
from fafycat.core.database import AppSettingsORM, CategoryORM, TransactionORM
from fafycat.ml.ensemble_categorizer import EnsembleCategorizer

MERCHANTS = {
    "groceries": ("EDEKA Markt", "Lastschrift Einkauf", -42.0),
    "dining": ("Pizzeria Napoli", "Abendessen", -28.0),
    "salary": ("ACME GmbH", "Gehalt", 3200.0),
}


def _txn(txn_id: str, name: str, purpose: str, amount: float, day: int, **fields) -> TransactionORM:
    return TransactionORM(
        id=txn_id,
        date=date(2024, 1, 1) + timedelta(days=day),
        value_date=date(2024, 1, 1) + timedelta(days=day),
        name=name,
        purpose=purpose,
        amount=amount,
        currency="EUR",
        import_batch="test",
        **fields,
    )


@pytest.fixture
def categories(db_session) -> dict[str, int]:
    """Three categories, by name."""
    rows = [
        CategoryORM(name="groceries", type="spending"),
        CategoryORM(name="dining", type="spending"),
        CategoryORM(name="salary", type="income"),
    ]
    db_session.add_all(rows)
    db_session.commit()
    return {str(row.name): int(row.id) for row in rows}


@pytest.fixture
def ensemble(db_session, categories, test_client) -> EnsembleCategorizer:
    """A real EnsembleCategorizer trained on 60 reviewed transactions, served by the API."""
    for name, (merchant, purpose, amount) in MERCHANTS.items():
        for i in range(20):
            db_session.add(
                _txn(
                    f"{name}-{i}",
                    f"{merchant} {i % 4}",
                    purpose,
                    amount - i,
                    day=i * 7,
                    category_id=categories[name],
                    predicted_category_id=categories[name],
                    is_reviewed=True,
                )
            )
    db_session.commit()

    model = EnsembleCategorizer(db_session, MLConfig())
    model.train()
    test_client.app.dependency_overrides[get_categorizer] = lambda: model
    return model


def test_predict_single_transaction_with_the_default_ensemble(test_client, ensemble, categories):
    response = test_client.post(
        "/api/ml/predict",
        json={"date": "2024-06-01", "name": "Pizzeria Napoli 2", "purpose": "Abendessen", "amount": -31.0},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["predicted_category_id"] == categories["dining"]
    assert data["predicted_category_name"] == "dining"
    assert 0.0 < data["confidence_score"] <= 1.0
    expected_level = (
        "High" if data["confidence_score"] >= 0.9 else "Medium" if data["confidence_score"] >= 0.7 else "Low"
    )
    assert data["confidence_level"] == expected_level


def test_predict_bulk_with_the_default_ensemble(test_client, ensemble, categories):
    response = test_client.post(
        "/api/ml/predict/bulk",
        json={
            "transactions": [
                {"date": "2024-06-01", "name": "EDEKA Markt 1", "purpose": "Lastschrift Einkauf", "amount": -50.0},
                {"date": "2024-06-02", "name": "ACME GmbH 0", "purpose": "Gehalt", "amount": 3200.0},
            ]
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total_processed"] == 2
    assert [p["predicted_category_name"] for p in data["predictions"]] == ["groceries", "salary"]
    assert [p["predicted_category_id"] for p in data["predictions"]] == [categories["groceries"], categories["salary"]]
    assert all(p["confidence_level"] in {"High", "Medium", "Low"} for p in data["predictions"])


def test_batch_unpredicted_predicts_pending_rows(test_client, ensemble, db_session):
    db_session.add(_txn("new-1", "EDEKA Markt 3", "Lastschrift Einkauf", -12.0, day=300))
    db_session.commit()

    response = test_client.post("/api/ml/predict/batch-unpredicted")

    assert response.status_code == 200, response.text
    assert response.json()["predictions_made"] == 1
    db_session.expire_all()
    assert db_session.get(TransactionORM, "new-1").predicted_category_id is not None


class TestBatchRepredictPaging:
    """batch-repredict must page through unreviewed rows and stop."""

    @pytest.fixture
    def unreviewed(self, db_session, ensemble, categories) -> list[str]:
        """Eleven unreviewed rows that stay below a 0.99 Auto-approve Threshold, so they keep matching."""
        db_session.add(AppSettingsORM(key="auto_approve_threshold", value="0.99"))
        ids = [f"open-{i:02d}" for i in range(11)]
        for i, txn_id in enumerate(ids):
            db_session.add(
                _txn(
                    txn_id,
                    "Kiosk am Eck",
                    "Kartenzahlung",
                    -10.0 - i,
                    day=200 + i,
                    predicted_category_id=categories["salary"],
                    confidence_score=0.4,
                    is_reviewed=False,
                )
            )
        db_session.commit()
        return ids

    def test_pages_cover_every_row_once_and_remaining_reaches_zero(self, test_client, db_session, unreviewed):
        seen_remaining = []
        made = 0
        cursor = None
        for _ in range(5):
            params = {"limit": 5, **({"after": cursor} if cursor else {})}
            body = test_client.post("/api/ml/predict/batch-repredict", params=params).json()
            made += body["predictions_made"]
            seen_remaining.append(body["remaining_unreviewed"])
            cursor = body["next_cursor"]
            if cursor is None:
                break

        assert seen_remaining == [6, 1, 0]
        assert made == 11
        db_session.expire_all()
        still_open = db_session.query(TransactionORM).filter(
            TransactionORM.id.in_(unreviewed), ~TransactionORM.is_reviewed
        )
        assert still_open.count() == 11

    def test_without_cursor_remaining_counts_rows_after_this_page(self, test_client, unreviewed):
        body = test_client.post("/api/ml/predict/batch-repredict", params={"limit": 5}).json()

        assert body["predictions_made"] == 5
        assert body["remaining_unreviewed"] == 6
        assert body["next_cursor"] == unreviewed[4]


def test_predict_invalid_request(test_client, ensemble):
    response = test_client.post("/api/ml/predict", json={"name": "Restaurant ABC"})
    assert response.status_code == 422


def test_predict_without_a_model_is_503(test_client):
    response = test_client.post(
        "/api/ml/predict", json={"date": "2024-01-20", "name": "Restaurant ABC", "purpose": "", "amount": -25.5}
    )

    assert response.status_code == 503
    assert "No trained" in response.json()["detail"]


def test_ml_status_without_a_model_cannot_predict(test_client):
    data = test_client.get("/api/ml/status").json()

    assert data["model_loaded"] is False
    assert data["can_predict"] is False
