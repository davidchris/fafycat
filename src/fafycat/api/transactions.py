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
from fafycat.web.components.transaction_table import (
    render_propagation_result,
    render_row,
    render_row_with_prompt,
    render_table,
)

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
    pattern, sibling_count = TransactionService.count_unreviewed_siblings(db, transaction_id)
    if sibling_count > 0:
        html = render_row_with_prompt(
            result,
            categories,
            pattern=pattern,
            sibling_count=sibling_count,
            # The stored name, not the submitted one: it is what propagate looks up.
            category_name=result.actual_category or actual_category,
        )
    else:
        html = render_row(result, categories)
    return HTMLResponse(content=html, status_code=200)


@router.post("/propagate", response_class=HTMLResponse)
async def propagate_category(
    source_id: str = Form(...),
    actual_category: str = Form(...),
    db: Session = Depends(get_db_session),
) -> HTMLResponse:
    """Apply a just-saved category to every unreviewed transaction with the same merchant pattern.

    Replaces the inline prompt with a confirmation and fires
    ``transactions-changed`` so the table reloads the rows that changed
    underneath the user.
    """
    result = TransactionService.propagate_category(session=db, source_id=source_id, category_name=actual_category)
    return HTMLResponse(
        content=render_propagation_result(source_id, result["applied"]),
        headers={"HX-Trigger": "transactions-changed"},
    )


@router.get("/propagate/dismiss", response_class=HTMLResponse)
async def dismiss_propagation_prompt() -> HTMLResponse:
    """Remove the propagation prompt row. Lets the prompt be dismissed without inline JS."""
    return HTMLResponse(content="")


@router.get("/table", response_class=HTMLResponse)
async def get_transactions_table(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str = Query("pending"),  # pending, reviewed, all
    sort_by: str = Query("confidence_score"),  # date, confidence_score, amount, name
    sort_order: str = Query("asc"),  # asc, desc
    search: str = Query(""),
    category_filter: str = Query(""),
    start_date: str = Query(""),
    end_date: str = Query(""),
    db: Session = Depends(get_db_session),
) -> HTMLResponse:
    """Get transactions table fragment for HTMX filtering with pagination."""
    # Convert status parameter to filters ("all" means no filter)
    is_reviewed = {"pending": False, "reviewed": True}.get(status)

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

    Sets is_reviewed=True and category_id=predicted_category_id for unreviewed
    transactions matching ``review_priority`` and/or ``min_confidence``. With
    neither given, the Auto-approve Threshold is the confidence floor.
    """
    return TransactionService.bulk_approve(
        session=db, review_priority=request.review_priority, min_confidence=request.min_confidence
    )
