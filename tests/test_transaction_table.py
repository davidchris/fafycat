"""Tests for the unified transaction-table renderer."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime

from fafycat.core.database import CategoryORM, TransactionORM
from fafycat.core.models import ReviewPriority


@dataclass
class FakeTransaction:
    """Minimal transaction-like object for rendering tests."""

    id: str = "abc123"
    date: str = "2025-06-15"
    description: str = "Test Store"
    amount: float = -10.0
    actual_category: str | None = None
    predicted_category: str | None = None
    confidence: float | None = 0.75
    is_reviewed: bool = False


def make_categories(*names: str) -> list[CategoryORM]:
    return [CategoryORM(name=name, type="spending", budget=0.0) for name in names]


class TestRenderRow:
    def test_unreviewed_row_shows_pending_state(self):
        from fafycat.web.components.transaction_table import render_row

        tx = FakeTransaction(predicted_category="Groceries")
        html = render_row(tx, make_categories("Groceries", "Rent"))

        assert 'id="transaction-abc123"' in html
        assert "Test Store" in html
        assert "€-10.00" in html
        assert "badge-saving" in html
        assert "Groceries" in html
        assert "Pending" in html
        assert "✓" not in html

    def test_reviewed_row_shows_confirmed_state(self):
        from fafycat.web.components.transaction_table import render_row

        tx = FakeTransaction(actual_category="Groceries", is_reviewed=True)
        html = render_row(tx, make_categories("Groceries"))

        assert "badge-success" in html
        assert "✓" in html
        assert "badge-saving" not in html
        assert "Complete" in html
        assert "text-success" in html

    def test_row_escapes_description_and_category_names(self):
        from fafycat.web.components.transaction_table import render_row

        payload = "<img src=x onerror=alert(1)>"
        tx = FakeTransaction(description=payload, predicted_category=payload)
        html = render_row(tx, make_categories(payload))

        assert payload not in html
        assert "&lt;img src=x onerror=alert(1)&gt;" in html

    def test_confidence_bands_color_the_confidence_cell(self):
        from fafycat.web.components.transaction_table import render_row

        categories = make_categories("Groceries")

        low = render_row(FakeTransaction(confidence=0.3), categories)
        assert "30.0%" in low
        assert "text-spending" in low

        mid = render_row(FakeTransaction(confidence=0.75), categories)
        assert "75.0%" in mid
        assert "text-income" in mid

        high = render_row(FakeTransaction(confidence=0.9), categories)
        assert "90.0%" in high
        assert "text-success" in high

        missing = render_row(FakeTransaction(confidence=None), categories)
        assert "N/A" in missing

    def test_row_form_targets_htmx_categorize_endpoint(self):
        from fafycat.web.components.transaction_table import render_row

        tx = FakeTransaction(id="tx42", predicted_category="Rent")
        html = render_row(tx, make_categories("Groceries", "Rent"))

        assert 'hx-put="/api/transactions/tx42/categorize-htmx"' in html
        assert 'hx-target="#transaction-tx42"' in html
        assert 'hx-swap="outerHTML"' in html
        assert 'name="actual_category"' in html
        assert '<option value="Rent" selected' in html
        assert '<option value="Groceries" selected' not in html


class TestRenderTable:
    def test_empty_list_renders_empty_state_card(self):
        from fafycat.web.components.transaction_table import render_table

        html = render_table([], make_categories("Groceries"))

        assert 'id="transaction-table"' in html
        assert "No transactions to review" in html
        assert "<table" not in html

    def test_table_wraps_rows_with_headers(self):
        from fafycat.web.components.transaction_table import render_table

        transactions = [FakeTransaction(id="t1"), FakeTransaction(id="t2", is_reviewed=True)]
        html = render_table(transactions, make_categories("Groceries"))

        assert 'id="transaction-table"' in html
        for header in ["Date", "Description", "Amount", "Current Category", "Categorize", "Status", "Confidence"]:
            assert f"{header}</th>" in html
        assert 'id="transaction-t1"' in html
        assert 'id="transaction-t2"' in html
        assert "pagination" not in html

    def test_pagination_info_adds_pagination_controls(self):
        from fafycat.web.components.transaction_table import render_table

        html = render_table(
            [FakeTransaction()],
            make_categories("Groceries"),
            pagination_info={"page": 2, "total_pages": 5, "total_count": 230},
        )

        assert "pagination-container" in html
        assert "Page 2 of 5" in html
        assert "230" in html


def _seed_transaction(session, *, name: str = "REWE", amount: float = -42.50) -> tuple[TransactionORM, CategoryORM]:
    """Insert one category and one unreviewed transaction predicted into it."""
    cat = CategoryORM(name="Groceries", type="spending", budget=0.0)
    session.add(cat)
    session.flush()

    txn_date = date(2025, 6, 15)
    raw = f"{txn_date.isoformat()}|{name}|{amount:.2f}"
    txn = TransactionORM(
        id=hashlib.md5(raw.encode()).hexdigest()[:16],
        date=txn_date,
        name=name,
        purpose="",
        amount=amount,
        currency="EUR",
        predicted_category_id=cat.id,
        confidence_score=0.6,
        is_reviewed=False,
        review_priority=ReviewPriority.HIGH,
        import_batch="test-batch",
        imported_at=datetime.now(UTC),
    )
    session.add(txn)
    session.flush()
    return txn, cat


class TestEndpointsServeUnifiedMarkup:
    def test_table_endpoint_uses_unified_renderer(self, test_client, db_session):
        _seed_transaction(db_session)

        resp = test_client.get("/api/transactions/table?status=all")

        assert resp.status_code == 200
        assert 'id="transaction-table"' in resp.text
        assert "€-42.50" in resp.text
        assert "$" not in resp.text

    def test_categorize_htmx_returns_unified_row(self, test_client, db_session):
        txn, cat = _seed_transaction(db_session)

        resp = test_client.put(
            f"/api/transactions/{txn.id}/categorize-htmx",
            data={"actual_category": cat.name},
        )

        assert resp.status_code == 200
        assert f'id="transaction-{txn.id}"' in resp.text
        assert "badge-success" in resp.text
        assert "✓" in resp.text
        assert "€-42.50" in resp.text
        # unified row keeps the table's cell styling (old fragment had drifted)
        assert "max-width: 24rem" in resp.text

    def test_review_page_uses_unified_renderer(self, test_client, db_session):
        txn, _ = _seed_transaction(db_session)
        db_session.commit()  # review page reads through its own session

        resp = test_client.get("/review")

        assert resp.status_code == 200
        assert f'id="transaction-{txn.id}"' in resp.text
        assert "€-42.50" in resp.text
