"""Tests for the review page's training-recency counter and retrain button."""

from datetime import date, datetime

import pytest
from fafycat.core.database import CategoryORM, ModelMetadataORM, ReviewEventORM, TransactionORM


@pytest.fixture
def groceries(db_session) -> int:
    """A single category to label transactions with."""
    db_session.query(TransactionORM).delete()
    db_session.query(CategoryORM).delete()
    db_session.commit()
    category = CategoryORM(name="groceries", type="spending")
    db_session.add(category)
    db_session.commit()
    return int(category.id)


def _seed_reviewed(db_session, category_id: int, count: int) -> None:
    """Add ``count`` reviewed transactions, each with a Review Event."""
    for i in range(count):
        txn_id = f"seed{i:04d}"
        db_session.add(
            TransactionORM(
                id=txn_id,
                date=date(2025, 1, (i % 28) + 1),
                name=f"Merchant {i}",
                amount=-10.0,
                import_batch="test",
                category_id=category_id,
                predicted_category_id=category_id,
                confidence_score=0.7,
                is_reviewed=True,
            )
        )
        db_session.add(
            ReviewEventORM(
                transaction_id=txn_id,
                created_at=datetime(2025, 2, 1),
                actor="user_review",
                to_category_id=category_id,
            )
        )
    db_session.commit()


def test_counter_and_button_render_when_training_is_possible(test_client, db_session, groceries):
    """With enough labelled data the page offers the one-click retrain."""
    _seed_reviewed(db_session, groceries, 60)

    html = test_client.get("/review").text

    assert 'id="training-recency-text"' in html
    assert "60 reviews recorded. The model has never been trained." in html
    assert 'id="retrain-repredict-btn"' in html
    assert "Retrain and re-predict the queue" in html
    assert 'id="retrain-alert"' in html


def test_counter_names_the_training_date(test_client, db_session, groceries):
    """Once a model is trained the counter shows its training date."""
    _seed_reviewed(db_session, groceries, 60)
    db_session.add(ModelMetadataORM(model_version="v1", training_date=datetime(2025, 1, 15), is_active=True))
    db_session.commit()

    html = test_client.get("/review").text

    assert "60 reviews since the model was last trained (15 Jan 2025)" in html


def test_button_hidden_until_there_is_enough_training_data(test_client, db_session, groceries):
    """Below the training minimum the page shows the shortfall, not the button."""
    _seed_reviewed(db_session, groceries, 3)

    html = test_client.get("/review").text

    assert 'id="retrain-repredict-btn"' not in html
    assert "Need at least 50 reviewed transactions to train (3 so far)." in html


def test_page_loads_the_review_controller_without_inline_handlers(test_client, db_session, groceries):
    """The retrain flow lives in review.js and binds by id, not via onclick."""
    _seed_reviewed(db_session, groceries, 60)

    html = test_client.get("/review").text

    assert "/static/js/review.js" in html
    assert "onclick=" not in html
    assert "onchange=" not in html
    assert "oninput=" not in html
