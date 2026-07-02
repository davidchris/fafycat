"""API routes for transaction operations."""

import contextlib
from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from fafycat.api.dependencies import get_db_session
from fafycat.api.models import BulkApproveRequest, BulkCategorizeRequest, TransactionResponse, TransactionUpdate
from fafycat.api.services import CategoryService, TransactionService
from fafycat.core.models import ReviewPriority
from fafycat.web.components.transaction_table import render_row, render_table

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("/", response_model=list[TransactionResponse])
async def get_transactions(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    category: str | None = Query(None),
    is_reviewed: bool | None = Query(None),
    confidence_lt: float | None = Query(None, ge=0, le=1),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    review_priority: ReviewPriority | None = Query(None),
    db: Session = Depends(get_db_session),
) -> list[TransactionResponse]:
    """Get transactions with filtering and pagination."""
    return TransactionService.get_transactions(
        session=db,
        skip=skip,
        limit=limit,
        category=category,
        is_reviewed=is_reviewed,
        confidence_lt=confidence_lt,
        start_date=start_date,
        end_date=end_date,
        review_priority=review_priority,
    )


@router.get("/pending", response_model=list[TransactionResponse])
async def get_pending_transactions(
    limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db_session)
) -> list[TransactionResponse]:
    """Get transactions that need review (low confidence or unreviewed)."""
    return TransactionService.get_pending_transactions(session=db, limit=limit)


@router.put("/{transaction_id}/category", response_model=TransactionResponse)
async def update_transaction_category(
    transaction_id: str, update: TransactionUpdate, db: Session = Depends(get_db_session)
) -> TransactionResponse:
    """Update the category of a specific transaction."""
    result = TransactionService.update_transaction_category(session=db, transaction_id=transaction_id, update=update)

    if not result:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return result


@router.put("/{transaction_id}/categorize-htmx", response_class=HTMLResponse)
async def categorize_transaction_htmx(
    transaction_id: str,
    actual_category: str = Form(...),
    db: Session = Depends(get_db_session),
) -> HTMLResponse:
    """HTMX-enabled categorization endpoint that returns HTML fragment."""
    update = TransactionUpdate(actual_category=actual_category, is_reviewed=True)
    result = TransactionService.update_transaction_category(session=db, transaction_id=transaction_id, update=update)

    if not result:
        return HTMLResponse(
            content="""
            <div class="alert alert-error">
                Transaction not found
            </div>
            """,
            status_code=404,
        )

    categories = CategoryService.get_categories(db)
    return HTMLResponse(content=render_row(result, categories), status_code=200)


@router.get("/table", response_class=HTMLResponse)
async def get_transactions_table(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str = Query("high_priority"),  # high_priority, pending, reviewed, all
    confidence_lt: float = Query(0.8, ge=0, le=1),
    sort_by: str = Query("date"),  # date, confidence, amount, description, category
    sort_order: str = Query("desc"),  # asc, desc
    search: str = Query(""),
    category_filter: str = Query(""),
    start_date: str = Query(""),
    end_date: str = Query(""),
    db: Session = Depends(get_db_session),
) -> HTMLResponse:
    """Get transactions table fragment for HTMX filtering with pagination."""
    # Convert status parameter to filters
    is_reviewed = None
    review_priority = None

    if status == "high_priority":
        is_reviewed = False
        review_priority = "high_priority"  # Special value for high + quality_check
    elif status == "pending":
        is_reviewed = False
    elif status == "reviewed":
        is_reviewed = True
    # status == "all" means no filters

    # Parse date filters
    parsed_start_date = None
    parsed_end_date = None

    if start_date:
        with contextlib.suppress(ValueError):
            parsed_start_date = date.fromisoformat(start_date)

    if end_date:
        with contextlib.suppress(ValueError):
            parsed_end_date = date.fromisoformat(end_date)

    # Calculate skip for pagination
    skip = (page - 1) * page_size

    # Get transactions with new parameters
    result = TransactionService.get_transactions_with_pagination(
        session=db,
        skip=skip,
        limit=page_size,
        is_reviewed=is_reviewed,
        confidence_lt=confidence_lt if status in ["pending", "high_priority"] else None,
        review_priority=review_priority,
        category=category_filter if category_filter else None,
        sort_by=sort_by,
        sort_order=sort_order,
        search=search,
        start_date=parsed_start_date,
        end_date=parsed_end_date,
    )

    categories = CategoryService.get_categories(db)

    return HTMLResponse(content=render_table(result["transactions"], categories, result["pagination_info"]))


@router.post("/bulk-categorize")
async def bulk_categorize_transactions(request: BulkCategorizeRequest, db: Session = Depends(get_db_session)) -> dict:
    """Bulk categorize multiple transactions."""
    updated_count = 0

    for transaction_id in request.transaction_ids:
        update = TransactionUpdate(actual_category=request.category)
        result = TransactionService.update_transaction_category(
            session=db, transaction_id=transaction_id, update=update
        )
        if result:
            updated_count += 1

    return {"updated": updated_count, "transaction_ids": request.transaction_ids}


@router.post("/bulk-approve")
async def bulk_approve_transactions(
    request: BulkApproveRequest = BulkApproveRequest(),
    db: Session = Depends(get_db_session),
) -> dict:
    """Bulk approve unreviewed transactions by trusting ML predictions.

    Sets is_reviewed=True and category_id=predicted_category_id for transactions
    matching the given review_priority (default: quality_check) that have not
    yet been reviewed.
    """
    return TransactionService.bulk_approve(
        session=db, review_priority=request.review_priority, min_confidence=request.min_confidence
    )
