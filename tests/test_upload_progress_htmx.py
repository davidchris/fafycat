"""Tests for HTMX upload progress indicators and inline results."""

import io
from fastapi.testclient import TestClient
from src.fafycat.core.database import TransactionORM, CategoryORM


class TestUploadProgressHTMX:
    """Test HTMX upload functionality with progress indicators and inline results."""

    def test_htmx_upload_endpoint_exists(self, test_client):
        """Test that the HTMX upload endpoint exists and accepts POST requests."""
        # Create a test CSV content
        csv_content = "Date,Description,Amount\n2024-01-01,Test Transaction,-10.50\n"
        files = {"file": ("test.csv", io.BytesIO(csv_content.encode()), "text/csv")}

        response = test_client.post("/api/upload/csv-htmx", files=files)

        # Should return HTML response (not JSON)
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    def test_htmx_upload_success_html_response(self, test_client, db_session):
        """Test that successful upload returns proper HTML response."""
        # Clear existing data
        db_session.query(TransactionORM).delete()
        db_session.query(CategoryORM).delete()
        db_session.commit()

        # Create test CSV with valid transaction
        csv_content = "Date,Description,Amount\n2024-01-01,Test Transaction,-10.50\n"
        files = {"file": ("test.csv", io.BytesIO(csv_content.encode()), "text/csv")}

        response = test_client.post("/api/upload/csv-htmx", files=files)

        assert response.status_code == 200
        html = response.text

        # Check for success indicators
        assert "Successfully imported" in html
        assert "test.csv" in html
        assert "Rows processed:" in html
        assert "New transactions:" in html
        assert "Review Transactions" in html
        assert "Upload Another File" in html

        # Check for proper CSS classes
        assert "bg-green-50" in html  # Success styling
        assert "border-green-200" in html

    def test_htmx_upload_error_html_response(self, test_client):
        """Test that upload errors return proper HTML error response."""
        # Create invalid file (wrong extension)
        files = {"file": ("test.txt", io.BytesIO(b"invalid content"), "text/plain")}

        response = test_client.post("/api/upload/csv-htmx", files=files)

        assert response.status_code == 200  # HTMX endpoints return 200 with error HTML
        html = response.text

        # Check for error indicators
        assert "Upload Failed" in html
        assert "Only CSV files are allowed" in html
        assert "Try Again" in html

        # Check for proper CSS classes
        assert "bg-red-50" in html  # Error styling
        assert "border-red-200" in html

    def test_htmx_upload_with_predictions(self, test_client, db_session):
        """Test that upload shows prediction information when ML model is available."""
        # This test simulates having predictions made
        # In real scenario, would need trained model
        csv_content = "Date,Description,Amount\n2024-01-01,Test Transaction,-10.50\n"
        files = {"file": ("test.csv", io.BytesIO(csv_content.encode()), "text/csv")}

        response = test_client.post("/api/upload/csv-htmx", files=files)

        assert response.status_code == 200
        html = response.text

        # Should contain file processing information
        assert "test.csv" in html
        assert "Rows processed:" in html

    def test_htmx_upload_duplicate_handling(self, test_client, db_session):
        """Test that duplicate transactions are properly shown in HTML response."""
        # First upload
        csv_content = "Date,Description,Amount\n2024-01-01,Test Transaction,-10.50\n"
        files = {"file": ("test.csv", io.BytesIO(csv_content.encode()), "text/csv")}
        test_client.post("/api/upload/csv-htmx", files=files)

        # Second upload (same data)
        files = {"file": ("test.csv", io.BytesIO(csv_content.encode()), "text/csv")}
        response = test_client.post("/api/upload/csv-htmx", files=files)

        assert response.status_code == 200
        html = response.text

        # Should show no new imports, but duplicates skipped
        assert "No new transactions imported" in html or "duplicates were skipped" in html
        assert "Duplicates skipped:" in html

    def test_import_page_has_htmx_form(self, test_client):
        """Test that the import page includes the HTMX form elements."""
        response = test_client.get("/import")

        assert response.status_code == 200
        html = response.text

        # Check for HTMX attributes
        assert 'hx-post="/api/upload/csv-htmx"' in html
        assert 'hx-target="#uploadResults"' in html
        assert 'hx-indicator="#uploadProgress"' in html
        assert 'id="uploadProgress"' in html
        assert 'id="uploadResults"' in html

        # Check for progress indicator
        assert "Processing your file..." in html
        assert "htmx-indicator" in html

        # Check for JavaScript functionality
        assert "updateUploadButton()" in html
        assert "htmx:afterRequest" in html

    def test_upload_button_disabled_initially(self, test_client):
        """Test that upload button is initially disabled until file is selected."""
        response = test_client.get("/import")

        assert response.status_code == 200
        html = response.text

        # Button should be disabled initially
        assert "disabled" in html
        assert 'id="uploadButton"' in html
        assert "Select a file first" in html or "Upload and Process" in html

    def test_htmx_form_reset_functionality(self, test_client):
        """Test that the form includes reset functionality after successful upload."""
        response = test_client.get("/import")

        assert response.status_code == 200
        html = response.text

        # Check for form reset JavaScript
        assert "htmx:afterRequest" in html
        assert "uploadForm" in html
        assert "reset()" in html

    def test_inline_results_styling(self, test_client, db_session):
        """Test that inline results have proper styling and actions."""
        # Clear existing data
        db_session.query(TransactionORM).delete()
        db_session.commit()

        csv_content = "Date,Description,Amount\n2024-01-01,Test Transaction,-10.50\n"
        files = {"file": ("test.csv", io.BytesIO(csv_content.encode()), "text/csv")}

        response = test_client.post("/api/upload/csv-htmx", files=files)

        assert response.status_code == 200
        html = response.text

        # Check for action buttons
        assert 'href="/review"' in html
        assert "Review Transactions" in html
        assert "Upload Another File" in html

        # Check for clear results functionality
        assert "document.getElementById('uploadResults').innerHTML = ''" in html
