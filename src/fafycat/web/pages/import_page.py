"""Import transactions page."""

from fastapi import Request

from fafycat.web.components.layout import create_page_layout


def _get_ml_status_sync():
    """Get ML status synchronously without HTTP calls."""
    try:
        import time

        start_time = time.time()

        from fafycat.core.config import AppConfig
        from fafycat.core.database import DatabaseManager, TransactionORM

        config = AppConfig()
        db_manager = DatabaseManager(config)

        with db_manager.get_session() as db_session:
            # Check for the correct model based on config (same logic as ML API)
            if config.ml.use_ensemble:
                model_path = config.ml.model_dir / "ensemble_categorizer.pkl"
            else:
                model_path = config.ml.model_dir / "categorizer.pkl"

            # Check training data readiness
            reviewed_count = (
                db_session.query(TransactionORM)
                .filter(TransactionORM.is_reviewed, TransactionORM.category_id.is_not(None))
                .count()
            )

            min_training_samples = 50
            training_ready = reviewed_count >= min_training_samples

            # Check unpredicted transactions
            unpredicted_count = (
                db_session.query(TransactionORM).filter(TransactionORM.predicted_category_id.is_(None)).count()
            )

            total_time = time.time() - start_time
            if total_time > 0.1:
                import logging

                logging.info("ML status sync (import) took %.3fs", total_time)

            if not model_path.exists():
                return {
                    "model_loaded": False,
                    "can_predict": False,
                    "training_ready": training_ready,
                    "reviewed_transactions": reviewed_count,
                    "min_training_samples": min_training_samples,
                    "unpredicted_transactions": unpredicted_count,
                }

            # If model exists, assume it's working (avoiding model loading here for speed)
            return {
                "model_loaded": True,
                "can_predict": True,
                "training_ready": training_ready,
                "reviewed_transactions": reviewed_count,
                "min_training_samples": min_training_samples,
                "unpredicted_transactions": unpredicted_count,
            }

    except Exception:
        return {
            "model_loaded": False,
            "can_predict": False,
            "training_ready": False,
            "reviewed_transactions": 0,
            "min_training_samples": 50,
            "unpredicted_transactions": 0,
        }


def _get_import_model_status_alert():
    """Get model status and return HTML alert for import page."""
    try:
        status = _get_ml_status_sync()

        # If model is working, show success message
        if status.get("model_loaded", False) and status.get("can_predict", False):
            return """
            <div class="alert alert-success">
                <h3>ML model ready for predictions</h3>
                <p>Imported transactions will receive automatic category predictions.</p>
            </div>
            """

        # Show warning that predictions won't work
        reviewed_count = status.get("reviewed_transactions", 0)
        training_ready = status.get("training_ready", False)

        if training_ready:
            return f"""
            <div class="alert alert-warning">
                <h3>No ML model trained yet</h3>
                <p>Imported transactions won't get automatic predictions. You have {reviewed_count} transactions ready for training.</p>
                <div class="mt-3">
                    <a href="/settings" class="btn btn-ghost">Train model first &rarr;</a>
                </div>
            </div>
            """

        return f"""
        <div class="alert alert-info">
            <h3>Building training data</h3>
            <p>Import and manually categorize transactions to build training data. You have {reviewed_count} so far (need 50+).</p>
        </div>
        """
    except Exception:
        pass
    return ""


def render_import_page(request: Request):
    """Render the import transactions page."""
    # Get model status alert
    model_alert = _get_import_model_status_alert()

    content = f"""
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-2xl font-bold mb-6">Import Transactions</h1>

        {model_alert}

        <div class="mb-8">
            <h2 class="text-lg font-semibold mb-4">Upload CSV File</h2>

            <!-- Upload Form with HTMX -->
            <div class="card">
                <form id="uploadForm"
                      hx-post="/api/upload/csv-htmx"
                      hx-target="#uploadResults"
                      hx-encoding="multipart/form-data"
                      hx-indicator="#uploadProgress"
                      class="space-y-4">

                    <div>
                        <label class="form-label">Select CSV file:</label>
                        <input type="file"
                               name="file"
                               id="fileInput"
                               accept=".csv"
                               class="form-input"
                               onchange="updateUploadButton()">
                    </div>

                    <button type="submit"
                            id="uploadButton"
                            disabled
                            class="btn btn-primary">
                        Upload and Process
                    </button>
                </form>

                <!-- Upload Progress Indicator -->
                <div id="uploadProgress" class="htmx-indicator mt-4">
                    <div class="alert alert-info" style="margin-bottom: 0;">
                        <div class="flex items-center">
                            <svg class="spinner mr-3 h-5 w-5 text-info" viewBox="0 0 24 24">
                                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle>
                                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                            </svg>
                            <div>
                                <p class="font-medium">Processing your file...</p>
                                <p class="text-sm text-secondary">This may take a few moments for large files</p>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Upload Results (will be populated by HTMX) -->
                <div id="uploadResults" class="mt-4"></div>
            </div>
        </div>

        <div class="card">
            <h2 class="text-lg font-semibold mb-4">Import Instructions</h2>
            <ul class="list-disc list-inside space-y-2">
                <li>CSV should contain columns: Date, Description, Amount, Account</li>
                <li>Date format should be YYYY-MM-DD or MM/DD/YYYY</li>
                <li>Amount should be numeric (negative for expenses, positive for income)</li>
                <li>Duplicate transactions will be automatically skipped</li>
            </ul>
        </div>
    </div>

    <script>
        function updateUploadButton() {{
            const fileInput = document.getElementById('fileInput');
            const uploadButton = document.getElementById('uploadButton');

            if (fileInput.files.length > 0) {{
                uploadButton.disabled = false;
                uploadButton.textContent = 'Upload and Process';
            }} else {{
                uploadButton.disabled = true;
                uploadButton.textContent = 'Select a file first';
            }}
        }}

        // Reset form after successful upload
        document.body.addEventListener('htmx:afterRequest', function(event) {{
            if (event.detail.xhr.status === 200 && event.detail.elt.id === 'uploadForm') {{
                // Reset form
                document.getElementById('uploadForm').reset();
                updateUploadButton();
            }}
        }});
    </script>
    """

    return create_page_layout("Import Transactions - FafyCat", content)
