"""Web routes for HTML pages."""

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from api.dependencies import get_db_manager
from api.models import TransactionUpdate
from api.services import TransactionService
from web.components.layout import create_page_layout

router = APIRouter()


@router.get("/app", response_class=HTMLResponse)
async def main_app(request: Request):
    """Main application page."""
    content = """
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-3xl font-bold text-center mb-8">🐱 FafyCat</h1>
        <p class="text-center text-gray-600 mb-8">Family Finance Categorizer</p>
        <p class="text-center">Welcome to the FastAPI + FastHTML version!</p>
    </div>
    """
    return create_page_layout("FafyCat - Family Finance Categorizer", content)


@router.get("/import", response_class=HTMLResponse)
async def import_page(request: Request):
    """Import transactions page."""
    from web.pages.import_page import render_import_page

    return render_import_page(request)


@router.get("/review", response_class=HTMLResponse)
async def review_page(request: Request):
    """Review and categorize transactions page."""
    from web.pages.review_page import render_review_page

    return render_review_page(request)


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Settings and categories page."""
    from web.pages.settings_page import render_settings_page

    return render_settings_page(request)


@router.post("/upload-csv", response_class=HTMLResponse)
async def upload_csv_web(request: Request, file: UploadFile):
    """Handle CSV upload and return HTML response with preview."""
    import os
    import tempfile
    from pathlib import Path

    from api.dependencies import get_db_manager

    # Get database manager and session
    db_manager = get_db_manager(request)

    try:
        with db_manager.get_session() as db_session:
            from src.fafycat.data.csv_processor import CSVProcessor

            # Save uploaded file temporarily
            file_content = await file.read()
            content_str = file_content.decode("utf-8")

            # Create temp file and ensure it's written and closed properly
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv") as tmp_file:
                tmp_file.write(content_str)
                tmp_file_path = tmp_file.name

            # Process the CSV
            processor = CSVProcessor(db_session)
            transactions, errors = processor.import_csv(Path(tmp_file_path))

            # Clean up temp file
            os.unlink(tmp_file_path)

            if errors:
                raise Exception(f"CSV processing errors: {'; '.join(errors[:5])}")

            if not transactions:
                raise Exception("No valid transactions found in CSV")

            # Save transactions to database
            new_count, duplicate_count = processor.save_transactions(transactions)

            # Create success page with results
            if new_count > 0:
                success_msg = f"✅ Successfully imported {new_count} new transactions!"
            else:
                success_msg = f"ℹ️ No new transactions imported. {duplicate_count} duplicates were skipped."

            content = f"""
            <div class="container mx-auto px-4 py-8">
                <h1 class="text-2xl font-bold mb-6">Upload Results</h1>

                <div class="bg-green-50 border border-green-200 rounded-lg p-6 mb-6">
                    <h2 class="text-lg font-semibold text-green-800 mb-2">{success_msg}</h2>
                    <div class="text-green-700">
                        <p><strong>File:</strong> {file.filename}</p>
                        <p><strong>Rows processed:</strong> {len(transactions)}</p>
                        <p><strong>New transactions:</strong> {new_count}</p>
                        <p><strong>Duplicates skipped:</strong> {duplicate_count}</p>
                    </div>
                </div>

                <div class="flex gap-4">
                    <a href="/import" class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600">
                        Import Another File
                    </a>
                    <a href="/review" class="bg-green-500 text-white px-4 py-2 rounded hover:bg-green-600">
                        Review Transactions
                    </a>
                </div>
            </div>
            """

            return create_page_layout("Upload Successful - FafyCat", content)

    except Exception as e:
        # Handle errors
        content = f"""
        <div class="container mx-auto px-4 py-8">
            <h1 class="text-2xl font-bold mb-6">Upload Error</h1>

            <div class="bg-red-50 border border-red-200 rounded-lg p-6 mb-6">
                <h2 class="text-lg font-semibold text-red-800 mb-2">❌ Upload Failed</h2>
                <p class="text-red-700">Error: {str(e)}</p>
            </div>

            <a href="/import" class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600">
                Try Again
            </a>
        </div>
        """

        return create_page_layout("Upload Error - FafyCat", content)


@router.post("/transactions/{transaction_id}/categorize", response_class=HTMLResponse)
async def categorize_transaction_web(
    request: Request,
    transaction_id: str,
    actual_category: str = Form(...),
):
    """Handle form submission for categorizing a transaction."""
    db_manager = get_db_manager(request)

    try:
        with db_manager.get_session() as session:
            # Update the transaction
            update = TransactionUpdate(actual_category=actual_category, is_reviewed=True)
            result = TransactionService.update_transaction_category(
                session=session, transaction_id=transaction_id, update=update
            )

            if not result:
                raise Exception("Transaction not found")

        # Redirect back to review page
        return RedirectResponse(url="/review", status_code=302)

    except Exception as e:
        # Handle error - could redirect with error message or show error page
        content = f"""
        <div class="container mx-auto px-4 py-8">
            <h1 class="text-2xl font-bold mb-6">Categorization Error</h1>

            <div class="bg-red-50 border border-red-200 rounded-lg p-6 mb-6">
                <h2 class="text-lg font-semibold text-red-800 mb-2">❌ Failed to categorize transaction</h2>
                <p class="text-red-700">Error: {str(e)}</p>
            </div>

            <a href="/review" class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600">
                Back to Review
            </a>
        </div>
        """

        return create_page_layout("Categorization Error - FafyCat", content)
