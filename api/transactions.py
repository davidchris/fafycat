"""API routes for transaction operations."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.dependencies import get_db_session
from api.models import TransactionResponse, TransactionUpdate, BulkCategorizeRequest
from api.services import TransactionService


router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("/", response_model=List[TransactionResponse])
async def get_transactions(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    category: Optional[str] = Query(None),
    is_reviewed: Optional[bool] = Query(None),
    confidence_lt: Optional[float] = Query(None, ge=0, le=1),
    db: Session = Depends(get_db_session)
) -> List[TransactionResponse]:
    """Get transactions with filtering and pagination."""
    return TransactionService.get_transactions(
        session=db,
        skip=skip,
        limit=limit,
        category=category,
        is_reviewed=is_reviewed,
        confidence_lt=confidence_lt
    )


@router.get("/pending", response_model=List[TransactionResponse])
async def get_pending_transactions(
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db_session)
) -> List[TransactionResponse]:
    """Get transactions that need review (low confidence or unreviewed)."""
    return TransactionService.get_pending_transactions(session=db, limit=limit)


@router.put("/{transaction_id}/category", response_model=TransactionResponse)
async def update_transaction_category(
    transaction_id: str,
    update: TransactionUpdate,
    db: Session = Depends(get_db_session)
) -> TransactionResponse:
    """Update the category of a specific transaction."""
    result = TransactionService.update_transaction_category(
        session=db,
        transaction_id=transaction_id,
        update=update
    )
    
    if not result:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    return result


@router.post("/bulk-categorize")
async def bulk_categorize_transactions(
    request: BulkCategorizeRequest,
    db: Session = Depends(get_db_session)
) -> dict:
    """Bulk categorize multiple transactions."""
    updated_count = 0
    
    for transaction_id in request.transaction_ids:
        update = TransactionUpdate(actual_category=request.category)
        result = TransactionService.update_transaction_category(
            session=db,
            transaction_id=transaction_id,
            update=update
        )
        if result:
            updated_count += 1
    
    return {"updated": updated_count, "transaction_ids": request.transaction_ids}