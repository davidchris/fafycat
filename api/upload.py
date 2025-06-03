"""API routes for file upload operations."""

import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from api.dependencies import get_db_session
from api.models import UploadResponse
from src.fafycat.data.csv_processor import CSVProcessor

router = APIRouter(prefix="/upload", tags=["upload"])

# Store upload sessions temporarily (in production, use Redis or database)
upload_sessions = {}


def _predict_transaction_categories(db: Session, transactions: list, new_count: int) -> int:
    """Predict categories for newly uploaded transactions."""
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

                # Update transactions with predictions
                for txn, prediction in zip(new_txns, predictions, strict=True):
                    txn.predicted_category_id = prediction.predicted_category_id
                    txn.confidence_score = prediction.confidence_score
                    predictions_made += 1

                db.commit()

        except Exception as e:
            # Don't fail upload if ML prediction fails, just log it
            import logging
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
