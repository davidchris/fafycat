"""Tests for API automation features: bulk-approve, date filtering, enriched responses."""

import hashlib
from datetime import date, datetime, UTC

import pytest

from src.fafycat.core.database import CategoryORM, TransactionORM


def _make_txn_id(name: str, d: date, amount: float) -> str:
    """Generate a deterministic transaction ID matching the app's logic."""
    raw = f"{d.isoformat()}|{name}|{amount:.2f}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _insert_category(session, name: str = "Groceries", cat_type: str = "spending") -> CategoryORM:
    cat = CategoryORM(name=name, type=cat_type, budget=0.0)
    session.add(cat)
    session.flush()
    return cat


def _insert_transaction(
    session,
    *,
    name: str = "REWE",
    txn_date: date = date(2025, 6, 15),
    amount: float = -42.50,
    predicted_category_id: int | None = None,
    confidence_score: float | None = None,
    is_reviewed: bool = False,
    review_priority: str = "standard",
    category_id: int | None = None,
) -> TransactionORM:
    txn_id = _make_txn_id(name, txn_date, amount)
    txn = TransactionORM(
        id=txn_id,
        date=txn_date,
        name=name,
        purpose="",
        amount=amount,
        currency="EUR",
        category_id=category_id,
        predicted_category_id=predicted_category_id,
        confidence_score=confidence_score,
        is_reviewed=is_reviewed,
        review_priority=review_priority,
        import_batch="test-batch",
        imported_at=datetime.now(UTC),
    )
    session.add(txn)
    session.flush()
    return txn


class TestBulkApproveEndpoint:
    """Tests for POST /api/transactions/bulk-approve."""

    def test_bulk_approve_quality_check(self, test_client, db_session):
        """Quality-check transactions become reviewed with correct category."""
        cat = _insert_category(db_session)
        txn = _insert_transaction(
            db_session,
            name="REWE Markt",
            predicted_category_id=cat.id,
            confidence_score=0.95,
            is_reviewed=False,
            review_priority="quality_check",
        )
        db_session.commit()

        # Default review_priority is now "quality_check"
        resp = test_client.post("/api/transactions/bulk-approve")
        assert resp.status_code == 200
        data = resp.json()
        assert data["approved"] == 1
        assert txn.id in data["transaction_ids"]

        # Verify DB state
        db_session.refresh(txn)
        assert txn.is_reviewed is True
        assert txn.category_id == cat.id

    def test_bulk_approve_with_min_confidence(self, test_client, db_session):
        """Transactions below min_confidence threshold are not approved."""
        cat = _insert_category(db_session)
        high = _insert_transaction(
            db_session,
            name="REWE High",
            amount=-50.0,
            predicted_category_id=cat.id,
            confidence_score=0.92,
            review_priority="quality_check",
        )
        low = _insert_transaction(
            db_session,
            name="REWE Low",
            amount=-30.0,
            predicted_category_id=cat.id,
            confidence_score=0.65,
            review_priority="quality_check",
        )
        db_session.commit()

        resp = test_client.post("/api/transactions/bulk-approve", json={"min_confidence": 0.9})
        assert resp.status_code == 200
        data = resp.json()
        assert data["approved"] == 1
        assert high.id in data["transaction_ids"]
        assert low.id not in data["transaction_ids"]

        db_session.refresh(low)
        assert low.is_reviewed is False

    def test_bulk_approve_empty_body_uses_defaults(self, test_client, db_session):
        """POST with empty body uses default review_priority='quality_check'."""
        cat = _insert_category(db_session)
        _insert_transaction(
            db_session,
            predicted_category_id=cat.id,
            confidence_score=0.9,
            review_priority="quality_check",
        )
        db_session.commit()

        resp = test_client.post("/api/transactions/bulk-approve")
        assert resp.status_code == 200
        assert resp.json()["approved"] == 1

    def test_bulk_approve_ignores_already_auto_accepted(self, test_client, db_session):
        """Auto-accepted transactions (is_reviewed=True) are not matched by default."""
        cat = _insert_category(db_session)
        _insert_transaction(
            db_session,
            predicted_category_id=cat.id,
            confidence_score=0.95,
            is_reviewed=True,
            review_priority="auto_accepted",
        )
        db_session.commit()

        resp = test_client.post("/api/transactions/bulk-approve")
        assert resp.status_code == 200
        assert resp.json()["approved"] == 0

    def test_bulk_approve_skips_already_reviewed(self, test_client, db_session):
        """Already-reviewed transactions are not re-approved."""
        cat = _insert_category(db_session)
        # quality_check but already reviewed — should be skipped
        _insert_transaction(
            db_session,
            predicted_category_id=cat.id,
            confidence_score=0.9,
            is_reviewed=True,
            review_priority="quality_check",
        )
        db_session.commit()

        resp = test_client.post("/api/transactions/bulk-approve", json={})
        assert resp.status_code == 200
        assert resp.json()["approved"] == 0


class TestDateFiltering:
    """Tests for date filtering on GET /api/transactions/."""

    def test_date_range_filtering(self, test_client, db_session):
        """Transactions outside the date range are excluded."""
        cat = _insert_category(db_session)
        _insert_transaction(db_session, name="Jan", txn_date=date(2025, 1, 15), amount=-10.0, category_id=cat.id)
        _insert_transaction(db_session, name="Mar", txn_date=date(2025, 3, 15), amount=-20.0, category_id=cat.id)
        _insert_transaction(db_session, name="Jun", txn_date=date(2025, 6, 15), amount=-30.0, category_id=cat.id)
        db_session.commit()

        resp = test_client.get("/api/transactions/", params={"start_date": "2025-02-01", "end_date": "2025-04-30"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["description"].startswith("Mar")

    def test_start_date_only(self, test_client, db_session):
        """Only start_date filters correctly."""
        _insert_transaction(db_session, name="Old", txn_date=date(2024, 1, 1), amount=-5.0)
        _insert_transaction(db_session, name="New", txn_date=date(2025, 6, 1), amount=-15.0)
        db_session.commit()

        resp = test_client.get("/api/transactions/", params={"start_date": "2025-01-01"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["description"].startswith("New")


class TestReviewPriorityInResponse:
    """Tests that review_priority appears in transaction responses."""

    def test_review_priority_field_present(self, test_client, db_session):
        """review_priority is included in GET /api/transactions/ response."""
        _insert_transaction(db_session, review_priority="quality_check")
        db_session.commit()

        resp = test_client.get("/api/transactions/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["review_priority"] == "quality_check"


class TestEnrichedUploadResponse:
    """Tests that upload response includes categorization summary fields."""

    def test_upload_response_has_categorization_fields(self, test_client, db_session):
        """Upload CSV response contains auto_accepted, needs_review, quality_check fields."""
        import tempfile
        from pathlib import Path

        # Create a minimal valid CSV
        csv_content = "date,name,purpose,amount,currency\n2025-01-01,Test Store,Purchase,-10.00,EUR\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            csv_path = Path(f.name)

        try:
            with open(csv_path, "rb") as fh:
                resp = test_client.post("/api/upload/csv", files={"file": ("test.csv", fh, "text/csv")})
            assert resp.status_code == 200
            data = resp.json()
            # These fields must be present (even if 0)
            assert "auto_accepted" in data
            assert "needs_review" in data
            assert "quality_check" in data
            assert "predictions_made" in data
        finally:
            csv_path.unlink()


class TestCLIImport:
    """Tests for the CLI import command."""

    def test_cmd_import_json_output_shape(self, db_session, monkeypatch):
        """cmd_import prints JSON with expected keys."""
        import io
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        csv_content = "date,name,purpose,amount,currency\n2025-01-01,Test Store,Purchase,-10.00,EUR\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            csv_path = Path(f.name)

        try:
            import argparse

            args = argparse.Namespace(file=str(csv_path), command="import")

            # Capture stdout
            captured = io.StringIO()

            # Patch DatabaseManager to use our test session
            with (
                patch("cli.AppConfig") as mock_config,
                patch("cli.DatabaseManager") as mock_db_manager,
                patch("sys.stdout", captured),
            ):
                mock_config.return_value.ensure_dirs.return_value = None
                mock_db_manager_instance = mock_db_manager.return_value
                mock_db_manager_instance.create_tables.return_value = None
                mock_db_manager_instance.get_session.return_value.__enter__ = lambda self: db_session
                mock_db_manager_instance.get_session.return_value.__exit__ = lambda self, *a: None

                from cli import cmd_import

                cmd_import(args)

            output = captured.getvalue()
            result = json.loads(output)
            assert "filename" in result
            assert "rows_processed" in result
            assert "transactions_imported" in result
            assert "duplicates_skipped" in result
        finally:
            csv_path.unlink()
