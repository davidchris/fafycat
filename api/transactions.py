"""API routes for transaction operations."""

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
            <div class="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded">
                Transaction not found
            </div>
            """,
            status_code=404,
        )

    # Generate updated table row
    status_color = "text-green-600" if result.is_reviewed else "text-yellow-600"
    status_text = "Complete" if result.is_reviewed else "Pending"
    confidence_display = f"{result.confidence:.1%}" if result.confidence else "N/A"

    # Get categories for the dropdown
    categories = CategoryService.get_categories(db)
    category_options = '<option value="">Select category...</option>'
    current_category = result.actual_category or result.predicted_category
    for cat in categories:
        selected = " selected" if cat.name == current_category else ""
        category_options += f'<option value="{cat.name}"{selected}>{cat.name}</option>'

    return HTMLResponse(
        content=f"""
        <tr id="transaction-{transaction_id}" class="border-b hover:bg-gray-50">
            <td class="px-4 py-3 text-sm">{result.date}</td>
            <td class="px-4 py-3 text-sm font-medium">{result.description}</td>
            <td class="px-4 py-3 text-sm text-right">${result.amount:,.2f}</td>
            <td class="px-4 py-3 text-sm">
                <span class="px-2 py-1 bg-green-100 text-green-800 rounded text-xs">
                    {result.actual_category} ✓
                </span>
            </td>
            <td class="px-4 py-3 text-sm">
                <form hx-put="/api/transactions/{transaction_id}/categorize-htmx"
                      hx-target="#transaction-{transaction_id}"
                      hx-swap="outerHTML"
                      hx-indicator="#loading-{transaction_id}"
                      class="flex gap-2 items-center">
                    <select name="actual_category" class="text-sm border border-gray-300 rounded px-2 py-1">
                        {category_options}
                    </select>
                    <button type="submit" class="px-3 py-1 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">
                        Save
                    </button>
                    <div id="loading-{transaction_id}" class="htmx-indicator text-xs text-gray-500">
                        Saving...
                    </div>
                </form>
            </td>
            <td class="px-4 py-3 text-sm {status_color}">{status_text}</td>
            <td class="px-4 py-3 text-sm text-center">{confidence_display}</td>
        </tr>
        """,
        status_code=200,
    )


@router.get("/table", response_class=HTMLResponse)
async def get_transactions_table(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str = Query("pending"),  # pending, reviewed, all
    confidence_lt: float = Query(0.8, ge=0, le=1),
    sort_by: str = Query("date"),  # date, confidence, amount, description, category
    sort_order: str = Query("desc"),  # asc, desc
    search: str = Query(""),
    db: Session = Depends(get_db_session),
) -> HTMLResponse:
    """Get transactions table fragment for HTMX filtering with pagination."""
    # Convert status parameter to is_reviewed filter
    is_reviewed = None
    if status == "pending":
        is_reviewed = False
    elif status == "reviewed":
        is_reviewed = True
    # status == "all" means is_reviewed = None (no filter)

    # Calculate skip for pagination
    skip = (page - 1) * page_size

    # Get transactions with new parameters
    result = TransactionService.get_transactions_with_pagination(
        session=db,
        skip=skip,
        limit=page_size,
        is_reviewed=is_reviewed,
        confidence_lt=confidence_lt if status == "pending" else None,
        sort_by=sort_by,
        sort_order=sort_order,
        search=search,
    )

    categories = CategoryService.get_categories(db)

    return HTMLResponse(
        content=_generate_transaction_table_htmx(result["transactions"], categories, result["pagination_info"])
    )


def _generate_transaction_table_htmx(transactions, categories, pagination_info=None):
    """Generate HTMX-enhanced transaction table HTML."""
    if not transactions:
        return """
        <div id="transaction-table" class="bg-white rounded-lg shadow p-6">
            <p class="text-center text-gray-500 py-8">No transactions to review at the moment.</p>
        </div>
        """

    # Generate table rows
    table_rows = ""
    for tx in transactions:
        confidence_color = (
            "text-red-600"
            if tx.confidence and tx.confidence < 0.5
            else "text-yellow-600"
            if tx.confidence and tx.confidence < 0.8
            else "text-green-600"
        )
        confidence_display = f"{tx.confidence:.1%}" if tx.confidence else "N/A"

        # Generate category options with current category selected
        current_category = tx.actual_category or tx.predicted_category
        category_options = '<option value="">Select category...</option>'
        for cat in categories:
            selected = " selected" if cat.name == current_category else ""
            category_options += f'<option value="{cat.name}"{selected}>{cat.name}</option>'

        # Status display
        status_color = "text-green-600" if tx.is_reviewed else "text-yellow-600"
        status_text = "Complete" if tx.is_reviewed else "Pending"

        table_rows += f"""
        <tr id="transaction-{tx.id}" class="border-b hover:bg-gray-50">
            <td class="px-4 py-3 text-sm">{tx.date}</td>
            <td class="px-4 py-3 text-sm font-medium">{tx.description}</td>
            <td class="px-4 py-3 text-sm text-right">${tx.amount:,.2f}</td>
            <td class="px-4 py-3 text-sm">
                <span class="px-2 py-1 bg-blue-100 text-blue-800 rounded text-xs">
                    {tx.actual_category or tx.predicted_category or "Uncategorized"}
                </span>
            </td>
            <td class="px-4 py-3 text-sm">
                <form hx-put="/api/transactions/{tx.id}/categorize-htmx"
                      hx-target="#transaction-{tx.id}"
                      hx-swap="outerHTML"
                      hx-indicator="#loading-{tx.id}"
                      class="flex gap-2 items-center">
                    <select name="actual_category" class="text-sm border border-gray-300 rounded px-2 py-1">
                        {category_options}
                    </select>
                    <button type="submit" class="px-3 py-1 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">
                        Save
                    </button>
                    <div id="loading-{tx.id}" class="htmx-indicator text-xs text-gray-500">
                        Saving...
                    </div>
                </form>
            </td>
            <td class="px-4 py-3 text-sm {status_color}">{status_text}</td>
            <td class="px-4 py-3 text-sm {confidence_color} font-medium text-center">{confidence_display}</td>
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
    <div id="transaction-table" class="bg-white rounded-lg shadow overflow-hidden">
        <table class="min-w-full divide-y divide-gray-200">
            <thead class="bg-gray-50">
                <tr>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Date</th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Description</th>
                    <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Amount</th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Current Category</th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Categorize</th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Status</th>
                    <th class="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Confidence</th>
                </tr>
            </thead>
            <tbody class="bg-white divide-y divide-gray-200">
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
