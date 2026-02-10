"""API routes for ML prediction operations."""

import asyncio
import time
from datetime import date
from typing import cast

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.dependencies import get_db_session
from api.ml_training_job import (
    TrainingPhase,
    complete_job,
    create_training_job,
    fail_job,
    get_current_job,
    get_executor,
    get_job_by_id,
    is_training_in_progress,
    set_job_running,
    update_job_phase,
)
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
from src.fafycat.ml.ensemble_categorizer import EnsembleCategorizer

router = APIRouter(prefix="/ml", tags=["ml"])

# Global categorizer instance (lazy-loaded)
_categorizer: TransactionCategorizer | EnsembleCategorizer | None = None
_config: AppConfig | None = None


def get_categorizer(db: Session = Depends(get_db_session)) -> TransactionCategorizer | EnsembleCategorizer:
    """Get or create the ML categorizer instance."""
    global _categorizer, _config

    if _categorizer is None or _config is None:
        _config = AppConfig()
        _config.ensure_dirs()

        # Choose between ensemble and single model based on config
        if _config.ml.use_ensemble:
            _categorizer = EnsembleCategorizer(db, _config.ml)
            model_path = _config.ml.model_dir / "ensemble_categorizer.pkl"
        else:
            _categorizer = TransactionCategorizer(db, _config.ml)
            model_path = _config.ml.model_dir / "categorizer.pkl"

        # Try to load saved model
        if model_path.exists():
            try:
                _categorizer.load_model(model_path)
            except Exception as e:
                error_msg = str(e)
                if "No module named 'fafycat'" in error_msg:
                    detail = (
                        "The ML model is corrupted (module path issue). "
                        "Please retrain the model using the Settings page or 'uv run scripts/train_model.py'"
                    )
                elif "no such table:" in error_msg:
                    detail = (
                        "Database schema is incomplete. "
                        "Please run 'uv run scripts/init_prod_db.py' and then retrain the model."
                    )
                else:
                    detail = (
                        f"Failed to load ML model: {error_msg}. "
                        "Please retrain the model using the Settings page or 'uv run scripts/train_model.py'"
                    )

                raise HTTPException(status_code=503, detail=detail) from e
        else:
            model_type = "ensemble" if _config.ml.use_ensemble else "single"
            raise HTTPException(
                status_code=503,
                detail=(
                    f"No trained {model_type} ML model found. Please train a model first using "
                    "'uv run scripts/train_model.py'"
                ),
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
                category_name = str(category.name) if category else "Unknown"
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
    try:
        from src.fafycat.core.database import TransactionORM

        config = AppConfig()
        model_filename = "ensemble_categorizer.pkl" if config.ml.use_ensemble else "categorizer.pkl"
        model_path = config.ml.model_dir / model_filename

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
                "classes_count": (
                    len(categorizer.classes_)
                    if hasattr(categorizer, "classes_") and categorizer.classes_ is not None
                    else 0
                ),
                "training_ready": training_ready,
                "reviewed_transactions": reviewed_count,
                "min_training_samples": min_training_samples,
                "unpredicted_transactions": unpredicted_count,
            }
        except HTTPException as he:
            # Extract the specific error message from the HTTPException
            error_detail = he.detail if hasattr(he, "detail") else str(he)
            return {
                "model_loaded": False,
                "model_path": str(model_path),
                "status": f"Model failed to load: {error_detail}",
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


def _run_training_sync() -> None:
    """Synchronous training function to run in executor."""
    global _categorizer, _config

    try:
        _config = AppConfig()
        _config.ensure_dirs()

        # Create a separate database manager and session for training
        from src.fafycat.core.database import DatabaseManager

        training_db_manager = DatabaseManager(_config)

        with training_db_manager.get_session() as training_session:
            update_job_phase(TrainingPhase.PREPARING_DATA)

            # Choose between ensemble and single model based on config
            if _config.ml.use_ensemble:
                ensemble_categorizer = EnsembleCategorizer(training_session, _config.ml)
                model_filename = "ensemble_categorizer.pkl"

                # Create progress callback to update job phases during training
                def progress_callback(phase_name: str) -> None:
                    phase_map = {
                        "training_nb": TrainingPhase.TRAINING_NB,
                        "optimizing_weights": TrainingPhase.OPTIMIZING_WEIGHTS,
                    }
                    if phase_name in phase_map:
                        update_job_phase(phase_map[phase_name])

                # Train ensemble with validation optimization
                update_job_phase(TrainingPhase.TRAINING_LGBM)
                cv_results = ensemble_categorizer.train_with_validation_optimization(
                    progress_callback=progress_callback
                )

                update_job_phase(TrainingPhase.SAVING_MODEL)

                result_data = {
                    "status": "success",
                    "message": "Ensemble model retrained successfully",
                    "accuracy": cv_results["validation_accuracy"],
                    "validation_accuracy": cv_results["validation_accuracy"],
                    "ensemble_weights": cv_results["best_weights"],
                    "model_path": str(_config.ml.model_dir / model_filename),
                    "training_samples": cv_results["n_training_samples"],
                    "validation_samples": cv_results["n_validation_samples"],
                }
            else:
                single_categorizer = TransactionCategorizer(training_session, _config.ml)
                model_filename = "categorizer.pkl"

                update_job_phase(TrainingPhase.TRAINING_LGBM)
                metrics = single_categorizer.train()

                update_job_phase(TrainingPhase.SAVING_MODEL)

                result_data = {
                    "status": "success",
                    "message": "Model retrained successfully",
                    "accuracy": metrics.accuracy,
                    "model_path": str(_config.ml.model_dir / model_filename),
                    "training_samples": len(single_categorizer.prepare_training_data()[0]),
                }

            # Save the trained model
            model_path = _config.ml.model_dir / model_filename
            if _config.ml.use_ensemble:
                ensemble_categorizer.save_model(model_path)
            else:
                single_categorizer.save_model(model_path)

        # Reset global categorizer to force reload
        _categorizer = None

        complete_job(result_data)

    except ValueError as e:
        fail_job(f"Training failed: {str(e)}")
    except Exception as e:
        fail_job(f"Retraining failed: {str(e)}")


@router.post("/retrain")
async def retrain_model() -> dict:
    """Start model retraining as a background job."""
    # Check if training already in progress
    if is_training_in_progress():
        current = get_current_job()
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Training already in progress",
                "job_id": current.job_id if current else None,
            },
        )

    # Create new job
    job = create_training_job()
    set_job_running()

    # Run training in background thread
    loop = asyncio.get_event_loop()
    loop.run_in_executor(get_executor(), _run_training_sync)

    return {
        "job_id": job.job_id,
        "status": "pending",
        "message": "Training job started",
    }


@router.get("/training-status/{job_id}")
async def get_training_status(job_id: str) -> dict:
    """Get status of a training job by ID."""
    job = get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Training job not found")

    return job.to_dict()


@router.get("/training-status")
async def get_current_training_status() -> dict:
    """Get status of current/latest training job."""
    job = get_current_job()
    if not job:
        raise HTTPException(status_code=404, detail="No training job found")

    return job.to_dict()


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
                date=cast(date, txn.date),
                value_date=cast(date, txn.value_date or txn.date),
                name=str(txn.name),
                purpose=str(txn.purpose or ""),
                amount=cast(float, txn.amount),
                currency=str(txn.currency),
            )
            txn_inputs.append(txn_input)

        # Get predictions
        predictions = categorizer.predict_with_confidence(txn_inputs)

        # Use active learning to set review priorities (same logic as upload)
        from src.fafycat.core.models import TransactionPrediction
        from src.fafycat.ml.active_learning import ActiveLearningSelector

        al_selector = ActiveLearningSelector(db)

        # Convert predictions to TransactionPrediction format for active learning
        al_predictions = []
        for txn, prediction in zip(unpredicted_txns, predictions, strict=True):
            al_pred = TransactionPrediction(
                transaction_id=txn.id,
                predicted_category_id=prediction.predicted_category_id,
                confidence_score=prediction.confidence_score,
                feature_contributions=prediction.feature_contributions,
            )
            al_predictions.append(al_pred)

        # Get active learning strategic selections
        max_review_items = min(20, len(al_predictions))  # Limit to 20 strategic selections
        strategic_selections = set(
            al_selector.select_for_review(al_predictions, max_items=max_review_items, strategy="uncertainty")
        )

        # Apply hybrid categorization: confidence + active learning priority
        predictions_made = 0
        auto_accepted = 0
        high_priority_review = 0
        standard_review = 0
        confidence_threshold = 0.95  # Conservative threshold for auto-acceptance

        for txn, prediction in zip(unpredicted_txns, predictions, strict=True):
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

        return {
            "status": "success",
            "message": f"Made predictions for {predictions_made} transactions",
            "predictions_made": predictions_made,
            "auto_accepted": auto_accepted,
            "high_priority_review": high_priority_review,
            "standard_review": standard_review,
            "remaining_unpredicted": max(0, len(unpredicted_txns) - limit) if len(unpredicted_txns) == limit else 0,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch prediction failed: {str(e)}") from e
