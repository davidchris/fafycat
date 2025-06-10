"""Web routes for HTML pages."""

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from api.dependencies import get_db_manager
from api.models import TransactionUpdate
from api.services import TransactionService
from web.components.alerts import create_info_alert, create_purple_alert, create_upload_result_alert
from web.components.buttons import create_action_button, create_button_group
from web.components.layout import create_page_layout

router = APIRouter()


@router.get("/app", response_class=HTMLResponse)
async def main_app(request: Request) -> HTMLResponse:
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
async def import_page(request: Request) -> HTMLResponse:
    """Import transactions page."""
    from web.pages.import_page import render_import_page

    return render_import_page(request)


@router.get("/review", response_class=HTMLResponse)
async def review_page(request: Request) -> HTMLResponse:
    """Review and categorize transactions page."""
    from web.pages.review_page import render_review_page

    return render_review_page(request)


@router.get("/export", response_class=HTMLResponse)
async def export_page(request: Request) -> HTMLResponse:
    """Export data configuration page."""
    from api.dependencies import get_db_manager
    from web.pages.export_page import create_export_page

    # Get database manager and session
    db_manager = get_db_manager(request)

    with db_manager.get_session() as db_session:
        return create_export_page(request, db_session)


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
    """Settings and categories page."""
    from api.dependencies import get_db_manager
    from web.pages.settings_page import render_settings_page

    # Get database manager and session
    db_manager = get_db_manager(request)

    with db_manager.get_session() as db_session:
        return render_settings_page(request, db_session)


@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request) -> HTMLResponse:
    """Analytics and financial insights page."""
    from api.dependencies import get_db_manager
    from web.pages.analytics_page import render_analytics_page

    # Get database manager and session
    db_manager = get_db_manager(request)

    with db_manager.get_session() as db_session:
        return render_analytics_page(request, db_session)


@router.post("/upload-csv", response_class=HTMLResponse)
async def upload_csv_web(request: Request, file: UploadFile) -> HTMLResponse:
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

            # Auto-predict categories for new transactions if model is available
            predictions_made = 0
            if new_count > 0:
                from api.upload import _predict_transaction_categories

                predictions_made = _predict_transaction_categories(db_session, transactions, new_count)

            # Create success page with results
            if new_count > 0:
                success_msg = f"✅ Successfully imported {new_count} new transactions!"
            else:
                success_msg = f"ℹ️ No new transactions imported. {duplicate_count} duplicates were skipped."

            # Build components
            upload_result = create_upload_result_alert(
                success_msg, file.filename, len(transactions), new_count, duplicate_count
            )

            prediction_component = ""
            if predictions_made > 0:
                prediction_component = str(
                    create_purple_alert(
                        "🤖 ML Predictions Made",
                        f"{predictions_made} transactions received automatic category predictions",
                    )
                )
            elif new_count > 0:
                prediction_component = str(
                    create_info_alert("ℹ️ No ML Predictions", "No trained model available", "Train a model", "/settings")
                )

            # Create action buttons
            import_button = create_action_button("Import Another File", "/import", "blue")
            review_button = create_action_button("Review Transactions", "/review", "green")
            buttons = create_button_group(import_button, review_button)

            content = f"""
            <div class="container mx-auto px-4 py-8">
                <h1 class="text-2xl font-bold mb-6">Upload Results</h1>
                {upload_result}
                {prediction_component}
                {buttons}
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


@router.post("/transactions/{transaction_id}/categorize", response_model=None)
async def categorize_transaction_web(
    request: Request,
    transaction_id: str,
    actual_category: str = Form(...),
) -> HTMLResponse | RedirectResponse:
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


@router.post("/api/export/summary", response_class=HTMLResponse)
async def export_summary_htmx(request: Request) -> str:
    """HTMX endpoint for export summary updates."""
    from api.export import ExportService
    from web.pages.export_page import create_export_summary_response

    db_manager = get_db_manager(request)

    try:
        # Get form data
        form_data = await request.form()

        # Parse form data
        start_date = form_data.get("start_date") or None
        end_date = form_data.get("end_date") or None
        categories = form_data.getlist("categories") or None

        # Convert date strings to date objects
        if start_date:
            from datetime import datetime

            start_date = datetime.fromisoformat(start_date).date()
        if end_date:
            from datetime import datetime

            end_date = datetime.fromisoformat(end_date).date()

        with db_manager.get_session() as db_session:
            from api.export import ExportService

            # Mock summary for now - in real implementation this would call the actual summary endpoint logic
            summary_data = {
                "total_transactions": 0,
                "reviewed_transactions": 0,
                "predicted_transactions": 0,
                "amount_statistics": {"total": 0, "min": 0, "max": 0, "avg": 0},
                "category_breakdown": {},
                "date_range": {},
                "filters_applied": {
                    "start_date": start_date.isoformat() if start_date else None,
                    "end_date": end_date.isoformat() if end_date else None,
                    "categories": categories,
                },
            }

            # Use the actual export service to get real data
            try:
                data = ExportService.get_export_data(
                    session=db_session,
                    start_date=start_date,
                    end_date=end_date,
                    categories=categories,
                )

                # Calculate real summary
                total_transactions = len(data)
                reviewed_transactions = sum(1 for d in data if d.get("is_reviewed"))
                predicted_transactions = sum(1 for d in data if d.get("predicted_category"))

                amounts = [d["amount"] for d in data]
                amount_stats = {
                    "total": sum(amounts),
                    "min": min(amounts) if amounts else 0,
                    "max": max(amounts) if amounts else 0,
                    "avg": sum(amounts) / len(amounts) if amounts else 0,
                }

                # Category breakdown
                category_breakdown = {}
                for d in data:
                    cat = d.get("category")
                    if cat:
                        if cat not in category_breakdown:
                            category_breakdown[cat] = {"count": 0, "total_amount": 0}
                        category_breakdown[cat]["count"] += 1
                        category_breakdown[cat]["total_amount"] += d["amount"]

                # Date range
                dates = [d["date"] for d in data if d.get("date")]
                date_range = {}
                if dates:
                    date_range = {
                        "earliest": min(dates),
                        "latest": max(dates),
                    }

                summary_data = {
                    "total_transactions": total_transactions,
                    "reviewed_transactions": reviewed_transactions,
                    "predicted_transactions": predicted_transactions,
                    "amount_statistics": amount_stats,
                    "category_breakdown": category_breakdown,
                    "date_range": date_range,
                    "filters_applied": {
                        "start_date": start_date.isoformat() if start_date else None,
                        "end_date": end_date.isoformat() if end_date else None,
                        "categories": categories,
                    },
                }
            except Exception:
                # Fall back to default summary if data retrieval fails
                pass

            return create_export_summary_response(summary_data)

    except Exception as e:
        # Return error state
        return f"""
        <h2 class="text-xl font-semibold mb-4">Export Preview</h2>
        <div class="bg-red-50 p-4 rounded-lg">
            <div class="text-red-600">Error loading export preview: {str(e)}</div>
        </div>
        """
