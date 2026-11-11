"""API routes for file upload operations."""

import html
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from fafycat.api.dependencies import get_db_session
from fafycat.api.models import UploadResponse
from fafycat.data.csv_processor import (
    DATE_ORDERS,
    MAX_REPORTED_ERRORS,
    CSVProcessor,
    DateOrder,
    format_import_errors,
)
from fafycat.ml.prediction_pipeline import CategorizationSummary, predict_new

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["upload"])

# Store upload sessions temporarily (in production, use Redis or database)
upload_sessions = {}

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
"""Largest accepted CSV upload. Counted while the upload is read, not taken from ``file.size``."""

_READ_CHUNK_BYTES = 256 * 1024


class UploadError(Exception):
    """An upload the user must fix. ``str()`` is safe to show; ``details`` lists row errors."""

    def __init__(self, message: str, details: list[str] | None = None, status_code: int = 400):
        super().__init__(message)
        self.details = details or []
        self.status_code = status_code


@dataclass(frozen=True)
class CsvUploadResult:
    """What one CSV upload imported."""

    filename: str
    rows_processed: int
    new_count: int
    duplicate_count: int
    categorization: dict
    unknown_categories: dict[str, int] = field(default_factory=dict)
    ambiguous_categories: dict[str, int] = field(default_factory=dict)
    transaction_ids: list[str] = field(default_factory=list)

    def label_warning(self) -> str | None:
        """Say which CSV category labels matched no single category, or None."""
        parts = []
        if self.unknown_categories:
            parts.append(f"no category is named {_label_list(self.unknown_categories)}")
        if self.ambiguous_categories:
            parts.append(f"more than one category is named {_label_list(self.ambiguous_categories)}")
        if not parts:
            return None
        count = sum(self.unknown_categories.values()) + sum(self.ambiguous_categories.values())
        return f"{count} rows were imported unreviewed because {' and '.join(parts)}."


def _label_list(labels: dict[str, int]) -> str:
    return ", ".join(f"'{label}' ({count}x)" for label, count in sorted(labels.items()))


def parse_date_order(value: str | None) -> DateOrder | None:
    """Read the optional ``date_order`` form field: ``dmy``, ``mdy``, or empty for auto-detect."""
    if not value:
        return None
    for order in DATE_ORDERS:
        if value == order:
            return order
    raise UploadError(f"Unknown date order {value!r}; use 'dmy' or 'mdy'")


async def _spool_upload(file: UploadFile) -> Path:
    """Copy the upload to a temp file, stopping as soon as it exceeds ``MAX_UPLOAD_BYTES``."""
    fd, name = tempfile.mkstemp(suffix=".csv")
    path = Path(name)
    try:
        with os.fdopen(fd, "wb") as out:
            total = 0
            while chunk := await file.read(_READ_CHUNK_BYTES):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise UploadError(f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)", status_code=413)
                out.write(chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


async def import_uploaded_csv(file: UploadFile, db: Session, date_order: DateOrder | None = None) -> CsvUploadResult:
    """Check, read, import and categorize one uploaded CSV. Every upload route uses this.

    Raises:
        UploadError: The file is not a CSV, is too large, or has errors. Nothing was imported.
    """
    filename = file.filename or ""
    if not filename.lower().endswith(".csv"):
        raise UploadError("Only CSV files are allowed")

    temp_path = await _spool_upload(file)
    try:
        processor = CSVProcessor(db)
        transactions, errors = processor.import_csv(temp_path, date_order=date_order)
    finally:
        temp_path.unlink(missing_ok=True)

    if errors:
        shown = errors[:MAX_REPORTED_ERRORS]
        if len(errors) > len(shown):
            shown.append(f"... and {len(errors) - len(shown)} more")
        raise UploadError(f"CSV processing errors: {format_import_errors(errors)}", details=shown)
    if not transactions:
        raise UploadError("No valid transactions found in CSV")

    new_count, duplicate_count = processor.save_transactions(transactions)
    return CsvUploadResult(
        filename=filename,
        rows_processed=len(transactions),
        new_count=new_count,
        duplicate_count=duplicate_count,
        categorization=predict_transaction_categories(db, transactions, new_count),
        unknown_categories=dict(processor.unknown_categories),
        ambiguous_categories=dict(processor.ambiguous_categories),
        transaction_ids=[t.generate_id() for t in transactions[:10]],
    )


def empty_categorization_summary(prediction_error: str | None = None) -> dict:
    """Return a zeroed categorization summary, with why nothing was predicted if that was a failure."""
    return {**CategorizationSummary().to_dict(), "prediction_error": prediction_error}


def predict_transaction_categories(db: Session, transactions: list, new_count: int) -> dict:
    """Predict categories for newly imported transactions via the Prediction Pipeline.

    The import itself always succeeds. Without a trained Categorizer the
    summary is empty; when the saved model cannot be loaded or prediction
    fails, ``prediction_error`` says why.
    """
    if new_count <= 0:
        return empty_categorization_summary()

    from fafycat.api.ml import load_categorizer

    try:
        categorizer = load_categorizer(db)
        summary = predict_new(db, categorizer, [t.generate_id() for t in transactions])
    except FileNotFoundError:
        logger.info("No ML model available for predictions during upload")
        return empty_categorization_summary()
    except Exception as e:
        logger.exception("ML prediction failed during upload")
        return empty_categorization_summary(prediction_error=str(e))

    return {**summary.to_dict(), "prediction_error": None}


@router.post("/csv", response_model=UploadResponse)
async def upload_csv(
    file: UploadFile = File(...),
    date_order: str | None = Form(None),
    db: Session = Depends(get_db_session),
) -> UploadResponse:
    """Upload and process a CSV file containing transactions."""
    try:
        result = await import_uploaded_csv(file, db, parse_date_order(date_order))
    except UploadError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    except Exception as e:
        logger.exception("CSV upload failed")
        raise HTTPException(status_code=500, detail=f"Upload processing failed: {str(e)}") from e

    upload_id = str(uuid.uuid4())

    # Store session info for potential preview/confirmation workflow
    upload_sessions[upload_id] = {
        "filename": result.filename,
        "total_rows": result.rows_processed,
        "imported": result.new_count,
        "duplicates": result.duplicate_count,
        "predictions_made": result.categorization["predictions_made"],
        "transaction_ids": result.transaction_ids,  # First 10, for preview
    }

    return UploadResponse(
        upload_id=upload_id,
        filename=result.filename,
        rows_processed=result.rows_processed,
        transactions_imported=result.new_count,
        duplicates_skipped=result.duplicate_count,
        **result.categorization,
    )


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
async def upload_csv_htmx(
    file: UploadFile = File(...),
    date_order: str | None = Form(None),
    db: Session = Depends(get_db_session),
) -> str:
    """Upload and process a CSV file, returning HTML results for HTMX."""
    try:
        result = await import_uploaded_csv(file, db, parse_date_order(date_order))
    except UploadError as e:
        return _render_upload_error(str(e) if not e.details else "CSV processing errors:", e.details)
    except Exception as e:
        logger.exception("CSV upload failed")
        return _render_upload_error(f"Upload processing failed: {str(e)}")

    cat_summary = result.categorization
    return _render_upload_success(
        filename=result.filename,
        rows_processed=result.rows_processed,
        new_count=result.new_count,
        duplicate_count=result.duplicate_count,
        predictions_made=cat_summary["predictions_made"],
        auto_accepted=cat_summary["auto_accepted"],
        needs_review=cat_summary["needs_review"],
        already_reviewed=cat_summary["already_reviewed"],
        prediction_error=cat_summary["prediction_error"],
        label_warning=result.label_warning(),
    )


def _kept_clause(already_reviewed: int) -> str:
    """Mention rows that kept the category the CSV supplied, if any."""
    return f", {already_reviewed} kept the category from the file" if already_reviewed else ""


def _render_upload_success(
    filename: str,
    rows_processed: int,
    new_count: int,
    duplicate_count: int,
    predictions_made: int,
    auto_accepted: int = 0,
    needs_review: int = 0,
    already_reviewed: int = 0,
    prediction_error: str | None = None,
    label_warning: str | None = None,
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
                <p>🤖 ML Predictions</p>
                <p>{predictions_made} transactions got predictions: {auto_accepted} auto-accepted, {needs_review} need your review{_kept_clause(already_reviewed)}.</p>
            </div>
        """
    elif new_count > 0 and prediction_error:
        prediction_info = f"""
            <div class="alert alert-warning">
                <p>⚠️ No ML Predictions</p>
                <p>{html.escape(prediction_error)} <a href="/settings">Go to Settings</a>.</p>
            </div>
        """
    elif new_count > 0:
        prediction_info = """
            <div class="alert alert-info">
                <p>ℹ️ No ML Predictions</p>
                <p>No trained model available. <a href="/settings">Train a model</a> to get automatic predictions.</p>
            </div>
        """

    label_info = ""
    if label_warning:
        label_info = f"""
            <div class="alert alert-warning">
                <p>⚠️ Category labels not matched</p>
                <p>{html.escape(label_warning)}</p>
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
                    {label_info}
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


def _render_upload_error(error_message: str, details: list[str] | None = None) -> str:
    """Render error message HTML for HTMX response, with one list item per row error."""
    detail_list = ""
    if details:
        items = "".join(f"<li>{html.escape(detail)}</li>" for detail in details)
        detail_list = f'<ul class="list-disc list-inside">{items}</ul>'
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
                    {detail_list}
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
