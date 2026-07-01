"""API routes for file upload operations."""

import html
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from fafycat.api.dependencies import get_db_session
from fafycat.api.models import UploadResponse
from fafycat.data.csv_processor import CSVProcessor
from fafycat.ml.prediction_pipeline import predict_new

router = APIRouter(prefix="/upload", tags=["upload"])

# Store upload sessions temporarily (in production, use Redis or database)
upload_sessions = {}


def empty_categorization_summary() -> dict:
    """Return a zeroed categorization summary."""
    return {
        "predictions_made": 0,
        "auto_accepted": 0,
        "needs_review": 0,
        "quality_check": 0,
    }


def predict_transaction_categories(db: Session, transactions: list, new_count: int) -> dict:
    """Predict categories for newly imported transactions via the Prediction Pipeline.

    Gracefully degrades to an empty categorization summary when no trained
    Categorizer is available - the import itself still succeeds.
    """
    if new_count <= 0:
        return empty_categorization_summary()

    try:
        from fafycat.api.ml import get_categorizer

        categorizer = get_categorizer(db)
        summary = predict_new(db, categorizer, [t.generate_id() for t in transactions])
    except Exception as e:
        _handle_prediction_error(e)
        return empty_categorization_summary()

    return {
        "predictions_made": summary.total,
        "auto_accepted": summary.auto_accepted,
        "needs_review": summary.high + summary.standard,
        "quality_check": summary.quality_check,
    }


def _handle_prediction_error(e: Exception):
    """Handle prediction errors gracefully."""
    import logging
    import traceback

    error_msg = str(e)
    if "No trained ML model found" in error_msg:
        logging.info("No ML model available for predictions during upload")
    else:
        logging.error("ML prediction failed during upload: %s", e)
        traceback.print_exc()


@router.post("/csv", response_model=UploadResponse)
async def upload_csv(file: UploadFile = File(...), db: Session = Depends(get_db_session)) -> UploadResponse:
    """Upload and process a CSV file containing transactions."""
    # Validate file type
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed")

    # Validate file size (limit to 10MB)
    if file.size and file.size > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")

    temp_file_path: Path | None = None
    try:
        # Create temporary file
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file_path = Path(temp_file.name)

        # Process CSV
        processor = CSVProcessor(db)
        transactions, errors = processor.import_csv(temp_file_path)

        if errors:
            raise HTTPException(
                status_code=400,
                detail=f"CSV processing errors: {'; '.join(errors[:5])}",  # Show first 5 errors
            )

        if not transactions:
            raise HTTPException(status_code=400, detail="No valid transactions found in CSV")

        # Save transactions to database
        new_count, duplicate_count = processor.save_transactions(transactions)

        # Auto-predict categories for new transactions if model is available
        cat_summary = predict_transaction_categories(db, transactions, new_count)

        upload_id = str(uuid.uuid4())

        # Store session info for potential preview/confirmation workflow
        upload_sessions[upload_id] = {
            "filename": file.filename,
            "total_rows": len(transactions),
            "imported": new_count,
            "duplicates": duplicate_count,
            "predictions_made": cat_summary["predictions_made"],
            "transaction_ids": [t.generate_id() for t in transactions[:10]],  # Store first 10 for preview
        }

        return UploadResponse(
            upload_id=upload_id,
            filename=file.filename,
            rows_processed=len(transactions),
            transactions_imported=new_count,
            duplicates_skipped=duplicate_count,
            **cat_summary,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload processing failed: {str(e)}") from e
    finally:
        if temp_file_path is not None:
            temp_file_path.unlink(missing_ok=True)


@router.get("/preview/{upload_id}")
async def get_upload_preview(upload_id: str, db: Session = Depends(get_db_session)) -> dict:
    """Get preview of uploaded transactions before confirmation."""
    if upload_id not in upload_sessions:
        raise HTTPException(status_code=404, detail="Upload session not found")

    session_data = upload_sessions[upload_id]

    # Get first few transactions for preview
    from fafycat.core.database import TransactionORM

    transactions = (
        db.query(TransactionORM).filter(TransactionORM.id.in_(session_data["transaction_ids"])).limit(5).all()
    )

    preview_data = []
    for txn in transactions:
        preview_data.append(
            {
                "id": txn.id,
                "date": txn.date.isoformat(),
                "description": f"{txn.name} - {txn.purpose}".rstrip(" -") if txn.purpose else txn.name,
                "amount": txn.amount,
                "currency": txn.currency,
            }
        )

    return {
        "upload_id": upload_id,
        "summary": {
            "filename": session_data["filename"],
            "total_rows": session_data["total_rows"],
            "imported": session_data["imported"],
            "duplicates": session_data["duplicates"],
            "predictions_made": session_data.get("predictions_made", 0),
        },
        "preview": preview_data,
    }


@router.post("/confirm/{upload_id}")
async def confirm_upload(upload_id: str, db: Session = Depends(get_db_session)) -> dict:
    """Confirm and finalize transaction import."""
    if upload_id not in upload_sessions:
        raise HTTPException(status_code=404, detail="Upload session not found")

    session_data = upload_sessions[upload_id]

    # Clean up session
    del upload_sessions[upload_id]

    return {
        "message": "Upload confirmed and transactions saved",
        "upload_id": upload_id,
        "summary": {
            "imported": session_data["imported"],
            "duplicates": session_data["duplicates"],
            "predictions_made": session_data.get("predictions_made", 0),
        },
    }


@router.post("/csv-htmx", response_class=HTMLResponse)
async def upload_csv_htmx(file: UploadFile = File(...), db: Session = Depends(get_db_session)) -> str:
    """Upload and process a CSV file, returning HTML results for HTMX."""
    temp_file_path: Path | None = None
    try:
        # Validate file type
        if not file.filename or not file.filename.endswith(".csv"):
            return _render_upload_error("Only CSV files are allowed")

        # Validate file size (limit to 10MB)
        if file.size and file.size > 10 * 1024 * 1024:
            return _render_upload_error("File too large (max 10MB)")

        # Create temporary file
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file_path = Path(temp_file.name)

        # Process CSV
        processor = CSVProcessor(db)
        transactions, errors = processor.import_csv(temp_file_path)

        if errors:
            return _render_upload_error(f"CSV processing errors: {'; '.join(errors[:3])}")

        if not transactions:
            return _render_upload_error("No valid transactions found in CSV")

        # Save transactions to database
        new_count, duplicate_count = processor.save_transactions(transactions)

        # Auto-predict categories for new transactions if model is available
        cat_summary = predict_transaction_categories(db, transactions, new_count)

        # Return success HTML
        return _render_upload_success(
            filename=file.filename,
            rows_processed=len(transactions),
            new_count=new_count,
            duplicate_count=duplicate_count,
            predictions_made=cat_summary["predictions_made"],
        )

    except Exception as e:
        return _render_upload_error(f"Upload processing failed: {str(e)}")
    finally:
        if temp_file_path is not None:
            temp_file_path.unlink(missing_ok=True)


def _render_upload_success(
    filename: str, rows_processed: int, new_count: int, duplicate_count: int, predictions_made: int
) -> str:
    """Render success message HTML for HTMX response."""
    alert_class = "alert-success" if new_count > 0 else "alert-info"

    if new_count > 0:
        primary_msg = f"✅ Successfully imported {new_count} new transactions!"
    else:
        primary_msg = f"ℹ️ No new transactions imported. {duplicate_count} duplicates were skipped."

    # Build prediction info
    prediction_info = ""
    if predictions_made > 0:
        prediction_info = f"""
            <div class="alert alert-ml">
                <p>🤖 ML Predictions & Smart Review</p>
                <p>{predictions_made} transactions got automatic predictions. High-confidence predictions were auto-accepted, while uncertain ones are prioritized for review.</p>
            </div>
        """
    elif new_count > 0:
        prediction_info = """
            <div class="alert alert-info">
                <p>ℹ️ No ML Predictions</p>
                <p>No trained model available. <a href="/settings">Train a model</a> to get automatic predictions.</p>
            </div>
        """

    return f"""
        <div class="alert {alert_class} upload-result">
            <div class="upload-result-header">
                <div class="upload-result-icon">
                    <svg class="h-6 w-6" viewBox="0 0 20 20" fill="currentColor">
                        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
                    </svg>
                </div>
                <div class="upload-result-body">
                    <h3 class="upload-result-title">{primary_msg}</h3>
                    <div class="upload-result-details">
                        <p><strong>File:</strong> {html.escape(filename)}</p>
                        <p><strong>Rows processed:</strong> {rows_processed}</p>
                        <p><strong>New transactions:</strong> {new_count}</p>
                        <p><strong>Duplicates skipped:</strong> {duplicate_count}</p>
                    </div>
                    {prediction_info}
                    <div class="upload-result-actions">
                        <a href="/review" class="btn btn-success btn-sm">
                            Review Transactions
                        </a>
                        <button onclick="document.getElementById('uploadResults').innerHTML = ''"
                                class="btn btn-secondary btn-sm">
                            Upload Another File
                        </button>
                    </div>
                </div>
            </div>
        </div>
    """


def _render_upload_error(error_message: str) -> str:
    """Render error message HTML for HTMX response."""
    return f"""
        <div class="alert alert-error upload-result">
            <div class="upload-result-header">
                <div class="upload-result-icon">
                    <svg class="h-6 w-6" viewBox="0 0 20 20" fill="currentColor">
                        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd" />
                    </svg>
                </div>
                <div class="upload-result-body">
                    <h3 class="upload-result-title">❌ Upload Failed</h3>
                    <p>{html.escape(error_message)}</p>
                    <div class="upload-result-actions">
                        <button onclick="document.getElementById('uploadResults').innerHTML = ''"
                                class="btn btn-secondary btn-sm">
                            Try Again
                        </button>
                    </div>
                </div>
            </div>
        </div>
    """
