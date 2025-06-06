"""Import transactions page."""

from fastapi import Request

from web.components.layout import create_page_layout


def _get_ml_status_sync():
    """Get ML status synchronously without HTTP calls."""
    try:
        import time

        start_time = time.time()

        from src.fafycat.core.config import AppConfig
        from src.fafycat.core.database import DatabaseManager, TransactionORM

        config = AppConfig()
        db_manager = DatabaseManager(config)

        with db_manager.get_session() as db_session:
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
            <div class="mb-6 bg-green-50 border border-green-200 rounded-lg p-4">
                <div class="flex items-center">
                    <div class="flex-shrink-0">
                        <svg class="h-5 w-5 text-green-400" viewBox="0 0 20 20" fill="currentColor">
                            <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
                        </svg>
                    </div>
                    <div class="ml-3">
                        <h3 class="text-sm font-medium text-green-800">
                            ML model ready for predictions
                        </h3>
                        <div class="mt-1 text-sm text-green-700">
                            <p>Imported transactions will receive automatic category predictions.</p>
                        </div>
                    </div>
                </div>
            </div>
            """

        # Show warning that predictions won't work
        reviewed_count = status.get("reviewed_transactions", 0)
        training_ready = status.get("training_ready", False)

        if training_ready:
            return f"""
            <div class="mb-6 bg-yellow-50 border border-yellow-200 rounded-lg p-4">
                <div class="flex items-start">
                    <div class="flex-shrink-0">
                        <svg class="h-5 w-5 text-yellow-400" viewBox="0 0 20 20" fill="currentColor">
                            <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
                        </svg>
                    </div>
                    <div class="ml-3 flex-1">
                        <h3 class="text-sm font-medium text-yellow-800">
                            No ML model trained yet
                        </h3>
                        <div class="mt-2 text-sm text-yellow-700">
                            <p>Imported transactions won't get automatic predictions. You have {reviewed_count} transactions ready for training.</p>
                        </div>
                        <div class="mt-3">
                            <a href="/settings" class="inline-flex items-center text-sm font-medium text-yellow-600 hover:text-yellow-500">
                                Train model first
                                <svg class="ml-1 h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                                    <path fill-rule="evenodd" d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-4.293-4.293a1 1 0 010-1.414z" clip-rule="evenodd" />
                                </svg>
                            </a>
                        </div>
                    </div>
                </div>
            </div>
            """

        return f"""
        <div class="mb-6 bg-blue-50 border border-blue-200 rounded-lg p-4">
            <div class="flex items-center">
                <div class="flex-shrink-0">
                    <svg class="h-5 w-5 text-blue-400" viewBox="0 0 20 20" fill="currentColor">
                        <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd" />
                    </svg>
                </div>
                <div class="ml-3">
                    <h3 class="text-sm font-medium text-blue-800">
                        Building training data
                    </h3>
                    <div class="mt-1 text-sm text-blue-700">
                        <p>Import and manually categorize transactions to build training data. You have {reviewed_count} so far (need 50+).</p>
                    </div>
                </div>
            </div>
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
            <div class="bg-white p-6 rounded-lg shadow">
                <form id="uploadForm" 
                      hx-post="/api/upload/csv-htmx" 
                      hx-target="#uploadResults"
                      hx-encoding="multipart/form-data"
                      hx-indicator="#uploadProgress"
                      class="space-y-4">
                    
                    <div>
                        <label class="block text-sm font-medium mb-2">Select CSV file:</label>
                        <input type="file" 
                               name="file" 
                               id="fileInput"
                               accept=".csv" 
                               class="block w-full border rounded p-2"
                               onchange="updateUploadButton()">
                    </div>
                    
                    <button type="submit" 
                            id="uploadButton"
                            disabled
                            class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 disabled:bg-gray-400 disabled:cursor-not-allowed">
                        Upload and Process
                    </button>
                </form>

                <!-- Upload Progress Indicator -->
                <div id="uploadProgress" class="htmx-indicator mt-4">
                    <div class="bg-blue-50 border border-blue-200 rounded-lg p-4">
                        <div class="flex items-center">
                            <svg class="animate-spin mr-3 h-5 w-5 text-blue-500" viewBox="0 0 24 24">
                                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle>
                                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                            </svg>
                            <div>
                                <p class="font-medium text-blue-800">Processing your file...</p>
                                <p class="text-sm text-blue-600">This may take a few moments for large files</p>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Upload Results (will be populated by HTMX) -->
                <div id="uploadResults" class="mt-4"></div>
            </div>
        </div>

        <div class="bg-gray-50 p-6 rounded-lg">
            <h2 class="text-lg font-semibold mb-4">Import Instructions</h2>
            <ul class="list-disc list-inside space-y-2 text-gray-700">
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
