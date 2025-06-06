"""API routes for ML prediction operations."""

import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.dependencies import get_db_session
from api.models import (
    BulkPredictRequest,
    BulkPredictResponse,
    TransactionPredictRequest,
    TransactionPredictResponse,
)
from src.fafycat.core.config import AppConfig
from src.fafycat.core.database import CategoryORM
from src.fafycat.core.models import TransactionInput
from src.fafycat.ml.categorizer import TransactionCategorizer

router = APIRouter(prefix="/ml", tags=["ml"])

# Global categorizer instance (lazy-loaded)
_categorizer: TransactionCategorizer | None = None
_config: AppConfig | None = None


def get_categorizer(db: Session = Depends(get_db_session)) -> TransactionCategorizer:
    """Get or create the ML categorizer instance."""
    global _categorizer, _config

    if _categorizer is None or _config is None:
        _config = AppConfig()
        _config.ensure_dirs()

        _categorizer = TransactionCategorizer(db, _config.ml)

        # Try to load saved model
        model_path = _config.ml.model_dir / "categorizer.pkl"
        if model_path.exists():
            try:
                _categorizer.load_model(model_path)
            except Exception as e:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        f"Failed to load ML model: {str(e)}. "
                        "Please train a model first using 'uv run scripts/train_model.py'"
                    ),
                ) from e
        else:
            raise HTTPException(
                status_code=503,
                detail="No trained ML model found. Please train a model first using 'uv run scripts/train_model.py'",
            )

    return _categorizer


@router.post("/predict", response_model=TransactionPredictResponse)
async def predict_transaction_category(
    request: TransactionPredictRequest,
    categorizer: TransactionCategorizer = Depends(get_categorizer),
    db: Session = Depends(get_db_session),
) -> TransactionPredictResponse:
    """Predict category for a single transaction."""
    try:
        # Convert to TransactionInput
        txn_input = TransactionInput(
            date=request.date,
            value_date=request.value_date or request.date,
            name=request.name,
            purpose=request.purpose,
            amount=request.amount,
            currency=request.currency,
        )

        # Get prediction with detailed explanation
        explanation = categorizer.get_prediction_explanation(txn_input)

        prediction = explanation["prediction"]
        category_name = explanation["category_name"]
        confidence_level = explanation["confidence_level"]
        merchant_suggestions = explanation.get("merchant_suggestions", [])

        return TransactionPredictResponse(
            predicted_category_id=prediction.predicted_category_id,
            predicted_category_name=category_name,
            confidence_score=prediction.confidence_score,
            feature_contributions=prediction.feature_contributions,
            confidence_level=confidence_level,
            merchant_suggestions=merchant_suggestions,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}") from e


@router.post("/predict/bulk", response_model=BulkPredictResponse)
async def predict_transactions_bulk(
    request: BulkPredictRequest,
    categorizer: TransactionCategorizer = Depends(get_categorizer),
    db: Session = Depends(get_db_session),
) -> BulkPredictResponse:
    """Predict categories for multiple transactions in batch."""
    start_time = time.time()

    try:
        # Convert to TransactionInput list
        txn_inputs = []
        for req in request.transactions:
            txn_input = TransactionInput(
                date=req.date,
                value_date=req.value_date or req.date,
                name=req.name,
                purpose=req.purpose,
                amount=req.amount,
                currency=req.currency,
            )
            txn_inputs.append(txn_input)

        # Get batch predictions
        predictions = categorizer.predict_with_confidence(txn_inputs)

        # Convert to response format
        response_predictions = []
        for prediction in predictions:
            # Get category name
            try:
                category = db.query(CategoryORM).filter(CategoryORM.id == prediction.predicted_category_id).first()
                category_name = category.name if category else "Unknown"
            except Exception:
                # Handle case where categories table doesn't exist (e.g., in tests)
                category_name = "Unknown"

            # Get confidence level
            confidence_level = categorizer._get_confidence_level(prediction.confidence_score)

            response_predictions.append(
                TransactionPredictResponse(
                    predicted_category_id=prediction.predicted_category_id,
                    predicted_category_name=category_name,
                    confidence_score=prediction.confidence_score,
                    feature_contributions=prediction.feature_contributions,
                    confidence_level=confidence_level,
                    merchant_suggestions=None,  # Skip for bulk to improve performance
                )
            )

        processing_time = (time.time() - start_time) * 1000  # Convert to milliseconds

        return BulkPredictResponse(
            predictions=response_predictions,
            total_processed=len(request.transactions),
            processing_time_ms=processing_time,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bulk prediction failed: {str(e)}") from e


@router.get("/status")
async def get_ml_status(
    db: Session = Depends(get_db_session),
) -> dict:
    """Get ML model status and training readiness information."""
    start_time = time.time()
    try:
        from src.fafycat.core.database import TransactionORM

        config = AppConfig()
        model_path = config.ml.model_dir / "categorizer.pkl"

        # Check training data readiness
        reviewed_count = (
            db.query(TransactionORM).filter(TransactionORM.is_reviewed, TransactionORM.category_id.is_not(None)).count()
        )

        min_training_samples = 50  # Match train_model.py default
        training_ready = reviewed_count >= min_training_samples

        # Check unpredicted transactions
        unpredicted_count = db.query(TransactionORM).filter(TransactionORM.predicted_category_id.is_(None)).count()

        if not model_path.exists():
            return {
                "model_loaded": False,
                "model_path": str(model_path),
                "status": "No model found - ready to train" if training_ready else "Not enough training data",
                "can_predict": False,
                "training_ready": training_ready,
                "reviewed_transactions": reviewed_count,
                "min_training_samples": min_training_samples,
                "unpredicted_transactions": unpredicted_count,
            }

        # Try to get categorizer
        try:
            categorizer = get_categorizer(db)
            return {
                "model_loaded": True,
                "model_path": str(model_path),
                "model_version": categorizer.model_version,
                "is_trained": categorizer.is_trained,
                "status": "Model loaded and ready",
                "can_predict": True,
                "classes_count": len(categorizer.classes_) if categorizer.classes_ is not None else 0,
                "training_ready": training_ready,
                "reviewed_transactions": reviewed_count,
                "min_training_samples": min_training_samples,
                "unpredicted_transactions": unpredicted_count,
            }
        except HTTPException:
            return {
                "model_loaded": False,
                "model_path": str(model_path),
                "status": "Model file exists but failed to load",
                "can_predict": False,
                "training_ready": training_ready,
                "reviewed_transactions": reviewed_count,
                "min_training_samples": min_training_samples,
                "unpredicted_transactions": unpredicted_count,
            }

    except Exception as e:
        return {
            "model_loaded": False,
            "status": f"Error checking model status: {str(e)}",
            "can_predict": False,
            "training_ready": False,
            "reviewed_transactions": 0,
            "min_training_samples": 50,
            "unpredicted_transactions": 0,
        }


@router.post("/retrain")
async def retrain_model(
    db: Session = Depends(get_db_session),
) -> dict:
    """Trigger model retraining with current transaction data."""
    try:
        global _categorizer, _config

        _config = AppConfig()
        _config.ensure_dirs()

        # Create new categorizer instance for training
        categorizer = TransactionCategorizer(db, _config.ml)

        # Train the model
        metrics = categorizer.train()

        # Save the trained model
        model_path = _config.ml.model_dir / "categorizer.pkl"
        categorizer.save_model(model_path)

        # Reset global categorizer to force reload
        _categorizer = None

        return {
            "status": "success",
            "message": "Model retrained successfully",
            "accuracy": metrics.accuracy,
            "model_path": str(model_path),
            "training_samples": len(categorizer.prepare_training_data()[0]),
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Training failed: {str(e)}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Retraining failed: {str(e)}") from e


@router.post("/predict/batch-unpredicted")
async def predict_unpredicted_transactions(
    categorizer: TransactionCategorizer = Depends(get_categorizer),
    db: Session = Depends(get_db_session),
    limit: int = 1000,
) -> dict:
    """Run ML predictions on transactions that don't have predictions yet."""
    try:
        from src.fafycat.core.database import TransactionORM
        from src.fafycat.core.models import TransactionInput

        # Get transactions without predictions
        try:
            unpredicted_txns = (
                db.query(TransactionORM).filter(TransactionORM.predicted_category_id.is_(None)).limit(limit).all()
            )
        except Exception:
            # Handle case where transactions table doesn't exist (e.g., in tests)
            unpredicted_txns = []

        if not unpredicted_txns:
            return {
                "status": "success",
                "message": "No transactions need prediction",
                "predictions_made": 0,
            }

        # Convert to TransactionInput for prediction
        txn_inputs = []
        for txn in unpredicted_txns:
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
        predictions_made = 0
        for txn, prediction in zip(unpredicted_txns, predictions, strict=True):
            txn.predicted_category_id = prediction.predicted_category_id
            txn.confidence_score = prediction.confidence_score
            predictions_made += 1

        db.commit()

        return {
            "status": "success",
            "message": f"Made predictions for {predictions_made} transactions",
            "predictions_made": predictions_made,
            "remaining_unpredicted": max(0, len(unpredicted_txns) - limit) if len(unpredicted_txns) == limit else 0,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch prediction failed: {str(e)}") from e
