"""API routes for transaction operations."""

import contextlib
import html
from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from api.dependencies import get_db_session
from api.models import BulkCategorizeRequest, TransactionResponse, TransactionUpdate
from api.services import CategoryService, TransactionService
from web.components.pagination import create_full_pagination

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("/", response_model=list[TransactionResponse])
async def get_transactions(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    category: str | None = Query(None),
    is_reviewed: bool | None = Query(None),
    confidence_lt: float | None = Query(None, ge=0, le=1),
    db: Session = Depends(get_db_session),
) -> list[TransactionResponse]:
    """Get transactions with filtering and pagination."""
    return TransactionService.get_transactions(
        session=db, skip=skip, limit=limit, category=category, is_reviewed=is_reviewed, confidence_lt=confidence_lt
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

    # Generate updated table row
    status_color = "text-success" if result.is_reviewed else "text-income"
    status_text = "Complete" if result.is_reviewed else "Pending"
    confidence_display = f"{result.confidence:.1%}" if result.confidence else "N/A"

    # Get categories for the dropdown
    categories = CategoryService.get_categories(db)
    category_options = '<option value="">Select category...</option>'
    current_category = result.actual_category or result.predicted_category
    for cat in categories:
        selected = " selected" if cat.name == current_category else ""
        escaped = html.escape(cat.name)
        category_options += f'<option value="{escaped}"{selected}>{escaped}</option>'

    return HTMLResponse(
        content=f"""
        <tr id="transaction-{transaction_id}">
            <td>{result.date}</td>
            <td>{html.escape(str(result.description))}</td>
            <td class="amount-cell">${result.amount:,.2f}</td>
            <td>
                <span class="badge badge-success">
                    {html.escape(str(result.actual_category))} ✓
                </span>
            </td>
            <td>
                <form hx-put="/api/transactions/{transaction_id}/categorize-htmx"
                      hx-target="#transaction-{transaction_id}"
                      hx-swap="outerHTML"
                      hx-indicator="#loading-{transaction_id}"
                      class="inline-form">
                    <select name="actual_category" class="form-select">
                        {category_options}
                    </select>
                    <button type="submit" class="btn btn-primary btn-sm">
                        Save
                    </button>
                    <div id="loading-{transaction_id}" class="htmx-indicator text-secondary">
                        Saving...
                    </div>
                </form>
            </td>
            <td class="{status_color}">{status_text}</td>
            <td class="text-center">{confidence_display}</td>
        </tr>
        """,
        status_code=200,
    )


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

    return HTMLResponse(
        content=_generate_transaction_table_htmx(result["transactions"], categories, result["pagination_info"])
    )


def _generate_transaction_table_htmx(transactions, categories, pagination_info=None):
    """Generate HTMX-enhanced transaction table HTML."""
    if not transactions:
        return """
        <div id="transaction-table" class="card">
            <p class="text-center text-secondary" style="padding: 2rem 0">No transactions to review at the moment.</p>
        </div>
        """

    # Generate table rows
    table_rows = ""
    for tx in transactions:
        confidence_color = (
            "text-spending"
            if tx.confidence and tx.confidence < 0.5
            else "text-income"
            if tx.confidence and tx.confidence < 0.8
            else "text-success"
        )
        confidence_display = f"{tx.confidence:.1%}" if tx.confidence else "N/A"

        # Generate category options with current category selected
        current_category = tx.actual_category or tx.predicted_category
        category_options = '<option value="">Select category...</option>'
        for cat in categories:
            selected = " selected" if cat.name == current_category else ""
            escaped = html.escape(cat.name)
            category_options += f'<option value="{escaped}"{selected}>{escaped}</option>'

        # Status display
        status_color = "text-success" if tx.is_reviewed else "text-income"
        status_text = "Complete" if tx.is_reviewed else "Pending"

        table_rows += f"""
        <tr id="transaction-{tx.id}">
            <td>{tx.date}</td>
            <td>{html.escape(str(tx.description))}</td>
            <td class="amount-cell">${tx.amount:,.2f}</td>
            <td>
                <span class="badge badge-saving">
                    {html.escape(str(tx.actual_category or tx.predicted_category or "Uncategorized"))}
                </span>
            </td>
            <td>
                <form hx-put="/api/transactions/{tx.id}/categorize-htmx"
                      hx-target="#transaction-{tx.id}"
                      hx-swap="outerHTML"
                      hx-indicator="#loading-{tx.id}"
                      class="inline-form">
                    <select name="actual_category" class="form-select">
                        {category_options}
                    </select>
                    <button type="submit" class="btn btn-primary btn-sm">
                        Save
                    </button>
                    <div id="loading-{tx.id}" class="htmx-indicator text-secondary">
                        Saving...
                    </div>
                </form>
            </td>
            <td class="{status_color}">{status_text}</td>
            <td class="{confidence_color} font-medium text-center">{confidence_display}</td>
        </tr>
        """

    # Generate pagination controls if pagination info is provided
    pagination_html = ""
    if pagination_info:
        page = pagination_info["page"]
        total_pages = pagination_info["total_pages"]
        total_count = pagination_info["total_count"]

        pagination_component = create_full_pagination(page, total_pages, total_count)
        pagination_html = str(pagination_component)

    return f"""
    <div id="transaction-table" class="table-container">
        <table>
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Description</th>
                    <th style="text-align: right">Amount</th>
                    <th>Current Category</th>
                    <th>Categorize</th>
                    <th>Status</th>
                    <th style="text-align: center">Confidence</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
        {pagination_html}
    </div>
    """


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
