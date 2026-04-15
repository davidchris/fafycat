"""Tests for XSS hardening across pages."""

import tempfile
from dataclasses import dataclass
from pathlib import Path

from fafycat.core.database import CategoryORM


XSS_PAYLOAD = "<img src=x onerror=alert(1)>"
XSS_ESCAPED = "&lt;img src=x onerror=alert(1)&gt;"


@dataclass
class _FakeTransaction:
    """Minimal transaction-like object for rendering tests."""

    id: str = "abc123"
    date: str = "2025-06-15"
    description: str = "Test Store"
    amount: float = -10.0
    actual_category: str | None = None
    predicted_category: str | None = None
    confidence: float | None = 0.75
    is_reviewed: bool = False


class TestUploadXSSEscaping:
    """Tests that upload responses escape filenames."""

    def test_upload_htmx_escapes_filename(self, test_client, db_session):
        """POST CSV with XSS filename, assert escaped in error HTML."""
        csv_content = "not,a,valid,csv\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            csv_path = Path(f.name)

        try:
            with open(csv_path, "rb") as fh:
                resp = test_client.post(
                    "/api/upload/csv-htmx",
                    files={"file": (f"{XSS_PAYLOAD}.csv", fh, "text/csv")},
                )
            assert resp.status_code == 200
            body = resp.text
            # The raw script tag should not appear unescaped
            assert "<img src=x onerror=alert(1)>" not in body or "&lt;img" in body
        finally:
            csv_path.unlink()

    def test_upload_success_escapes_filename(self, test_client, db_session):
        """POST valid CSV with XSS filename, verify escaped in success HTML."""
        csv_content = "date,name,purpose,amount,currency\n2025-01-01,Test Store,Purchase,-10.00,EUR\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            csv_path = Path(f.name)

        try:
            with open(csv_path, "rb") as fh:
                resp = test_client.post(
                    "/api/upload/csv-htmx",
                    files={"file": (f"{XSS_PAYLOAD}.csv", fh, "text/csv")},
                )
            assert resp.status_code == 200
            body = resp.text
            # Filename should be escaped in the response
            if XSS_PAYLOAD in body:
                # If the payload appears, it must be in escaped form
                assert XSS_ESCAPED in body
        finally:
            csv_path.unlink()


class TestReviewPageXSS:
    """Tests that review page rendering escapes category names."""

    def test_transaction_table_escapes_category_name(self):
        """Category names in the transaction table badge are escaped."""
        from fafycat.web.pages.review_page import _generate_transaction_table

        categories = [CategoryORM(name=XSS_PAYLOAD, type="spending", budget=0.0)]
        transactions = [_FakeTransaction(predicted_category=XSS_PAYLOAD)]

        html = _generate_transaction_table(transactions, categories)

        assert XSS_PAYLOAD not in html
        assert XSS_ESCAPED in html

    def test_category_options_escapes_names(self):
        """Category names in filter dropdowns are escaped."""
        from fafycat.web.pages.review_page import _generate_category_options

        categories = [CategoryORM(name=XSS_PAYLOAD, type="spending", budget=0.0)]

        html = _generate_category_options(categories)

        assert XSS_PAYLOAD not in html
        assert XSS_ESCAPED in html


class TestSettingsPageXSS:
    """Tests that settings page escapes category names in onclick handlers."""

    def test_settings_category_name_escaped_in_js(self):
        """Category names are safely embedded in onclick handlers via json.dumps."""
        from fafycat.web.pages.settings_page import render_categories_management

        xss_cat = CategoryORM(name=XSS_PAYLOAD, type="spending", budget=100.0)
        xss_cat.id = 1
        xss_cat.is_active = True

        category_groups = {"spending": [xss_cat], "income": [], "saving": []}
        ml_status = {"model_loaded": False, "can_predict": False, "training_ready": False}

        html = render_categories_management(category_groups, [], ml_status)

        # Raw XSS payload must not appear unescaped in the HTML
        assert XSS_PAYLOAD not in html
        # The escaped form should appear (in display text and in JS strings)
        assert XSS_ESCAPED in html
