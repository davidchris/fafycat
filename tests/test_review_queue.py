"""The review queue: ordered by how much one review resolves, siblings shown on the row."""

import hashlib
from datetime import UTC, date, datetime

from fafycat.api.services import TransactionService
from fafycat.core.database import CategoryORM, TransactionORM
from fafycat.core.models import ReviewPriority


def _seed(session, *, name: str, pattern: str, confidence: float | None, reviewed: bool = False) -> TransactionORM:
    cat = session.query(CategoryORM).filter(CategoryORM.name == "Groceries").first()
    if cat is None:
        cat = CategoryORM(name="Groceries", type="spending", budget=0.0)
        session.add(cat)
        session.flush()
    raw = f"{name}|{pattern}|{confidence}|{reviewed}"
    txn = TransactionORM(
        id=hashlib.md5(raw.encode()).hexdigest()[:16],
        date=date(2026, 3, 1),
        name=name,
        purpose="",
        amount=-10.0,
        currency="EUR",
        merchant_pattern=pattern,
        predicted_category_id=cat.id,
        confidence_score=confidence,
        category_id=cat.id if reviewed else None,
        is_reviewed=reviewed,
        review_priority=ReviewPriority.AUTO_ACCEPTED if reviewed else ReviewPriority.HIGH,
        import_batch="test-batch",
        imported_at=datetime.now(UTC),
    )
    session.add(txn)
    session.flush()
    return txn


class TestReviewImpactOrdering:
    def test_pending_siblings_times_uncertainty_decides_the_order(self, db_session):
        _seed(db_session, name="REWE 1", pattern="REWE", confidence=0.5)  # 2 x 0.5 = 1.0
        _seed(db_session, name="REWE 2", pattern="REWE", confidence=0.85)  # 2 x 0.15 = 0.3
        _seed(db_session, name="Kiosk", pattern="KIOSK", confidence=0.2)  # 1 x 0.8 = 0.8
        _seed(db_session, name="REWE 3", pattern="REWE", confidence=0.99, reviewed=True)  # not pending

        result = TransactionService.get_transactions_with_pagination(
            db_session, is_reviewed=False, sort_by="review_impact", sort_order="desc"
        )

        names = [t.description for t in result["transactions"]]
        assert names == ["REWE 1", "Kiosk", "REWE 2"]

    def test_rows_without_a_pattern_count_as_their_own_sibling(self, db_session):
        _seed(db_session, name="Mystery", pattern="", confidence=0.1)  # 1 x 0.9
        _seed(db_session, name="Other mystery", pattern=None, confidence=0.95)  # 1 x 0.05
        _seed(db_session, name="REWE", pattern="REWE", confidence=0.6)  # 1 x 0.4

        result = TransactionService.get_transactions_with_pagination(
            db_session, is_reviewed=False, sort_by="review_impact", sort_order="desc"
        )

        assert [t.description for t in result["transactions"]] == ["Mystery", "REWE", "Other mystery"]

    def test_unpredicted_rows_count_as_fully_uncertain(self, db_session):
        _seed(db_session, name="REWE", pattern="REWE", confidence=0.6)
        _seed(db_session, name="New shop", pattern="NEW SHOP", confidence=None)

        result = TransactionService.get_transactions_with_pagination(
            db_session, is_reviewed=False, sort_by="review_impact", sort_order="desc"
        )

        assert [t.description for t in result["transactions"]] == ["New shop", "REWE"]

    def test_confidence_ordering_is_still_available(self, db_session):
        _seed(db_session, name="REWE 1", pattern="REWE", confidence=0.5)
        _seed(db_session, name="Kiosk", pattern="KIOSK", confidence=0.2)

        result = TransactionService.get_transactions_with_pagination(
            db_session, is_reviewed=False, sort_by="confidence_score", sort_order="asc"
        )

        assert [t.description for t in result["transactions"]] == ["Kiosk", "REWE 1"]


class TestSiblingCountOnTheRow:
    def test_response_carries_the_pending_sibling_count(self, db_session):
        _seed(db_session, name="REWE 1", pattern="REWE", confidence=0.5)
        _seed(db_session, name="REWE 2", pattern="REWE", confidence=0.7)
        _seed(db_session, name="REWE 3", pattern="REWE", confidence=0.9, reviewed=True)
        _seed(db_session, name="Kiosk", pattern="KIOSK", confidence=0.2)

        result = TransactionService.get_transactions_with_pagination(db_session, is_reviewed=False)

        by_name = {t.description: t.pending_siblings for t in result["transactions"]}
        assert by_name == {"REWE 1": 2, "REWE 2": 2, "Kiosk": 1}

    def test_table_names_the_other_pending_rows_of_the_merchant(self, test_client, db_session):
        _seed(db_session, name="REWE 1", pattern="REWE", confidence=0.5)
        _seed(db_session, name="REWE 2", pattern="REWE", confidence=0.7)
        _seed(db_session, name="REWE 3", pattern="REWE", confidence=0.6)
        _seed(db_session, name="Kiosk", pattern="KIOSK", confidence=0.2)

        resp = test_client.get("/api/transactions/table?status=pending")

        assert resp.status_code == 200
        assert resp.text.count("+2 pending alike") == 3
        assert "+0 pending" not in resp.text and "+1 pending" not in resp.text

    def test_review_page_defaults_to_review_impact(self, test_client, db_session):
        _seed(db_session, name="REWE 1", pattern="REWE", confidence=0.5)

        resp = test_client.get("/review")

        assert resp.status_code == 200
        assert '<option value="review_impact" selected>' in resp.text
        assert '<option value="desc" selected>' in resp.text
