"""Tests for the calibration report rendered beside the auto-approve threshold."""

from datetime import date

import pytest
from fafycat.core.database import AppSettingsORM, CategoryORM, TransactionORM


@pytest.fixture
def model_on_disk(tmp_data_dir):
    """A stand-in model file so the settings page takes its 'model loaded' branch."""
    (tmp_data_dir / "models" / "ensemble_categorizer.pkl").write_bytes(b"not a real model")
    return tmp_data_dir


@pytest.fixture
def reviewed_history(db_session):
    """Reviewed transactions spread across the confidence bands."""
    db_session.query(TransactionORM).delete()
    db_session.query(CategoryORM).delete()
    db_session.commit()

    groceries = CategoryORM(name="groceries", type="spending")
    restaurants = CategoryORM(name="restaurants", type="spending")
    db_session.add_all([groceries, restaurants])
    db_session.commit()

    # (id, confidence, actual category, review priority)
    rows = [
        ("low1", 0.20, restaurants, "standard"),
        ("low2", 0.30, groceries, "standard"),
        ("mid1", 0.85, groceries, "standard"),
        ("top1", 0.97, groceries, "auto_accepted"),
        ("top2", 0.98, restaurants, "auto_accepted"),
    ]
    for txn_id, confidence, category, priority in rows:
        db_session.add(
            TransactionORM(
                id=txn_id,
                date=date(2025, 1, 1),
                name=f"Merchant {txn_id}",
                amount=-10.0,
                import_batch="test",
                confidence_score=confidence,
                category_id=category.id,
                predicted_category_id=groceries.id,
                is_reviewed=True,
                review_priority=priority,
            )
        )
    db_session.commit()
    return db_session


def test_settings_page_renders_the_calibration_table(test_client, model_on_disk, reviewed_history):
    """The ML settings subsection carries a band-by-band agreement table."""
    html = test_client.get("/settings").text

    assert "How well calibrated is the model?" in html
    assert "Auto-Approve Threshold" in html
    for label in ["0.00-0.50", "0.50-0.80", "0.80-0.90", "0.90-0.95", "0.95-1.00"]:
        assert label in html


def test_table_reports_agreement_and_auto_accept_overrides(test_client, model_on_disk, reviewed_history):
    """Counts and the auto-accept override total reach the page."""
    html = test_client.get("/settings").text

    # One of the two auto-accepted transactions was corrected.
    assert "Auto-accepted transactions later corrected:\n            1." in html
    # The 0.80-0.90 band has a single review that kept the prediction.
    assert "100%" in html
    # The lowest band had one of two reviews keep the prediction.
    assert "50%" in html


def test_bands_above_the_threshold_are_marked(test_client, db_session, model_on_disk, reviewed_history):
    """Bands the current threshold already auto-accepts carry the 'auto' marker."""
    db_session.add(AppSettingsORM(key="auto_approve_threshold", value="0.9"))
    db_session.commit()

    html = test_client.get("/settings").text

    assert 'title="Auto-accepted at the current threshold"' in html
    # 0.90-0.95 and 0.95-1.00 are auto-accepted at 0.9; the three lower bands are not.
    assert html.count('title="Auto-accepted at the current threshold"') == 2


def test_empty_history_renders_the_table_without_rates(test_client, model_on_disk, db_session):
    """With nothing reviewed the bands still render, with an em dash for the rate."""
    db_session.query(TransactionORM).delete()
    db_session.commit()

    html = test_client.get("/settings").text

    assert "How well calibrated is the model?" in html
    assert "&mdash;" in html
