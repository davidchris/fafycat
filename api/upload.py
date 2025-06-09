"""API routes for file upload operations."""

import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from api.dependencies import get_db_session
from api.models import UploadResponse
from src.fafycat.data.csv_processor import CSVProcessor

router = APIRouter(prefix="/upload", tags=["upload"])

# Store upload sessions temporarily (in production, use Redis or database)
upload_sessions = {}


def _predict_transaction_categories(db: Session, transactions: list, new_count: int) -> int:
    """Predict categories for newly uploaded transactions with active learning selection."""
    predictions_made = 0
    if new_count > 0:
        try:
            from api.ml import get_categorizer

            categorizer = get_categorizer(db)

            # Get newly imported transactions for prediction
            new_transaction_ids = [t.generate_id() for t in transactions]
            from src.fafycat.core.database import TransactionORM

            new_txns = (
                db.query(TransactionORM)
                .filter(TransactionORM.id.in_(new_transaction_ids))
                .filter(TransactionORM.predicted_category_id.is_(None))  # Only predict for unpredicted transactions
                .all()
            )

            if new_txns:
                # Convert to TransactionInput for prediction
                txn_inputs = []
                for txn in new_txns:
                    from src.fafycat.core.models import TransactionInput

                    txn_input = TransactionInput(
                        date=txn.date,
                        value_date=txn.value_date or txn.date,
                        name=txn.name,
                        purpose=txn.purpose or "",
                        amount=txn.amount,
                        currency=txn.currency,
                    )
                    txn_inputs.append(txn_input)

                # Get predictions
                predictions = categorizer.predict_with_confidence(txn_inputs)

                # Use hybrid approach: confidence-first with active learning prioritization
                from src.fafycat.ml.active_learning import ActiveLearningSelector

                al_selector = ActiveLearningSelector(db)

                # Convert predictions to TransactionPrediction format for active learning
                from src.fafycat.core.models import TransactionPrediction

                al_predictions = []
                for txn, prediction in zip(new_txns, predictions, strict=True):
                    al_pred = TransactionPrediction(
                        transaction_id=txn.id,
                        predicted_category_id=prediction.predicted_category_id,
                        confidence_score=prediction.confidence_score,
                        feature_contributions=prediction.feature_contributions,
                    )
                    al_predictions.append(al_pred)

                # Get active learning strategic selections from ALL predictions
                max_review_items = min(20, len(al_predictions))  # Limit to 20 strategic selections
                strategic_selections = set(
                    al_selector.select_for_review(al_predictions, max_items=max_review_items, strategy="uncertainty")
                )

                # Hybrid categorization: confidence + active learning priority
                auto_accepted = 0
                high_priority_review = 0
                standard_review = 0
                confidence_threshold = 0.95  # Conservative threshold for auto-acceptance

                for txn, prediction in zip(new_txns, predictions, strict=True):
                    txn.predicted_category_id = prediction.predicted_category_id
                    txn.confidence_score = prediction.confidence_score

                    if prediction.confidence_score >= confidence_threshold:
                        # High confidence - check if active learning flagged it for quality validation
                        if txn.id in strategic_selections:
                            # High confidence but flagged for quality check
                            txn.is_reviewed = False
                            txn.review_priority = "quality_check"
                            high_priority_review += 1
                        else:
                            # High confidence and not flagged - auto accept
                            txn.category_id = prediction.predicted_category_id  # Copy predicted to actual category
                            txn.is_reviewed = True
                            txn.review_priority = "auto_accepted"
                            auto_accepted += 1
                    else:
                        # Lower confidence - definitely needs review
                        txn.is_reviewed = False
                        if txn.id in strategic_selections:
                            txn.review_priority = "high"
                            high_priority_review += 1
                        else:
                            txn.review_priority = "standard"
                            standard_review += 1

                    predictions_made += 1

                db.commit()

        except Exception as e:
            # Don't fail upload if ML prediction fails, just log it
            import logging

            # Check if this is expected "no model" case vs actual error
            error_msg = str(e)
            if "No trained ML model found" in error_msg:
                logging.info(
                    "No ML model available for predictions during upload - this is expected for new installations"
                )
            else:
                logging.warning("ML prediction failed during upload: %s", e)

    return predictions_made


@router.post("/csv", response_model=UploadResponse)
async def upload_csv(file: UploadFile = File(...), db: Session = Depends(get_db_session)) -> UploadResponse:
    """Upload and process a CSV file containing transactions."""
    # Validate file type
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed")

    # Validate file size (limit to 10MB)
    if file.size and file.size > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")

    try:
        # Create temporary file
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file_path = Path(temp_file.name)

        # Process CSV
        processor = CSVProcessor(db)
        transactions, errors = processor.import_csv(temp_file_path)

        # Clean up temp file
        temp_file_path.unlink()

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
        predictions_made = _predict_transaction_categories(db, transactions, new_count)

        upload_id = str(uuid.uuid4())

        # Store session info for potential preview/confirmation workflow
        upload_sessions[upload_id] = {
            "filename": file.filename,
            "total_rows": len(transactions),
            "imported": new_count,
            "duplicates": duplicate_count,
            "predictions_made": predictions_made,
            "transaction_ids": [t.generate_id() for t in transactions[:10]],  # Store first 10 for preview
        }

        return UploadResponse(
            upload_id=upload_id,
            filename=file.filename,
            rows_processed=len(transactions),
            transactions_imported=new_count,
            duplicates_skipped=duplicate_count,
            predictions_made=predictions_made,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload processing failed: {str(e)}") from e


@router.get("/preview/{upload_id}")
async def get_upload_preview(upload_id: str, db: Session = Depends(get_db_session)) -> dict:
    """Get preview of uploaded transactions before confirmation."""
    if upload_id not in upload_sessions:
        raise HTTPException(status_code=404, detail="Upload session not found")

    session_data = upload_sessions[upload_id]

    # Get first few transactions for preview
    from src.fafycat.core.database import TransactionORM

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

        # Clean up temp file
        temp_file_path.unlink()

        if errors:
            return _render_upload_error(f"CSV processing errors: {'; '.join(errors[:3])}")

        if not transactions:
            return _render_upload_error("No valid transactions found in CSV")

        # Save transactions to database
        new_count, duplicate_count = processor.save_transactions(transactions)

        # Auto-predict categories for new transactions if model is available
        predictions_made = _predict_transaction_categories(db, transactions, new_count)

        # Return success HTML
        return _render_upload_success(
            filename=file.filename,
            rows_processed=len(transactions),
            new_count=new_count,
            duplicate_count=duplicate_count,
            predictions_made=predictions_made,
        )

    except Exception as e:
        return _render_upload_error(f"Upload processing failed: {str(e)}")


def _render_upload_success(
    filename: str, rows_processed: int, new_count: int, duplicate_count: int, predictions_made: int
) -> str:
    """Render success message HTML for HTMX response."""
    # Determine the primary message and style
    if new_count > 0:
        primary_msg = f"✅ Successfully imported {new_count} new transactions!"
        bg_color = "bg-green-50"
        border_color = "border-green-200"
        text_color = "text-green-800"
        icon_color = "text-green-400"
        secondary_color = "text-green-700"
    else:
        primary_msg = f"ℹ️ No new transactions imported. {duplicate_count} duplicates were skipped."
        bg_color = "bg-blue-50"
        border_color = "border-blue-200"
        text_color = "text-blue-800"
        icon_color = "text-blue-400"
        secondary_color = "text-blue-700"

    # Build prediction info
    prediction_info = ""
    if predictions_made > 0:
        prediction_info = f"""
            <div class="mt-3 p-3 bg-purple-50 border border-purple-200 rounded">
                <p class="text-sm font-medium text-purple-800">🤖 ML Predictions & Smart Review</p>
                <p class="text-sm text-purple-700">{predictions_made} transactions got automatic predictions. High-confidence predictions were auto-accepted, while uncertain ones are prioritized for review.</p>
            </div>
        """
    elif new_count > 0:
        # Show info about no predictions when transactions were imported but no model available
        prediction_info = """
            <div class="mt-3 p-3 bg-blue-50 border border-blue-200 rounded">
                <p class="text-sm font-medium text-blue-800">ℹ️ No ML Predictions</p>
                <p class="text-sm text-blue-700">No trained model available. <a href="/settings" class="underline hover:text-blue-600">Train a model</a> to get automatic predictions.</p>
            </div>
        """

    return f"""
        <div class="{bg_color} {border_color} border rounded-lg p-6">
            <div class="flex items-start">
                <div class="flex-shrink-0">
                    <svg class="h-6 w-6 {icon_color}" viewBox="0 0 20 20" fill="currentColor">
                        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
                    </svg>
                </div>
                <div class="ml-3 flex-1">
                    <h3 class="text-lg font-semibold {text_color} mb-2">{primary_msg}</h3>
                    <div class="space-y-1 {secondary_color}">
                        <p><strong>File:</strong> {filename}</p>
                        <p><strong>Rows processed:</strong> {rows_processed}</p>
                        <p><strong>New transactions:</strong> {new_count}</p>
                        <p><strong>Duplicates skipped:</strong> {duplicate_count}</p>
                    </div>
                    {prediction_info}
                    <div class="mt-4 flex gap-3">
                        <a href="/review" class="inline-flex items-center px-3 py-2 text-sm font-medium text-white bg-green-600 rounded-md hover:bg-green-700">
                            Review Transactions
                        </a>
                        <button onclick="document.getElementById('uploadResults').innerHTML = ''"
                                class="inline-flex items-center px-3 py-2 text-sm font-medium {text_color} bg-transparent border border-current rounded-md hover:bg-current hover:bg-opacity-10">
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
        <div class="bg-red-50 border border-red-200 rounded-lg p-6">
            <div class="flex items-start">
                <div class="flex-shrink-0">
                    <svg class="h-6 w-6 text-red-400" viewBox="0 0 20 20" fill="currentColor">
                        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd" />
                    </svg>
                </div>
                <div class="ml-3 flex-1">
                    <h3 class="text-lg font-semibold text-red-800 mb-2">❌ Upload Failed</h3>
                    <p class="text-red-700">{error_message}</p>
                    <div class="mt-4">
                        <button onclick="document.getElementById('uploadResults').innerHTML = ''"
                                class="inline-flex items-center px-3 py-2 text-sm font-medium text-red-800 bg-transparent border border-red-300 rounded-md hover:bg-red-50">
                            Try Again
                        </button>
                    </div>
                </div>
            </div>
        </div>
    """
