"""Transaction table renderer shared by the review page and HTMX endpoints."""

from fasthtml.common import Button, Div, Form, Option, P, Select, Span, Table, Tbody, Td, Th, Thead, Tr, to_xml

from fafycat.web.components.pagination import create_full_pagination


def _category_select(tx, categories) -> Select:
    """Category dropdown with the transaction's current category preselected."""
    current = tx.actual_category or tx.predicted_category
    options = [Option("Select category...", value="")]
    for cat in categories:
        options.append(Option(cat.name, value=cat.name, selected=cat.name == current))
    return Select(*options, name="actual_category", cls="form-select")


def _confidence_color(confidence: float | None) -> str:
    if confidence and confidence < 0.5:
        return "text-spending"
    if confidence and confidence < 0.8:
        return "text-income"
    return "text-success"


def _row(tx, categories) -> Tr:
    """Build a transaction row with its HTMX categorization form."""
    category_name = tx.actual_category or tx.predicted_category or "Uncategorized"
    confidence_display = f"{tx.confidence:.1%}" if tx.confidence else "N/A"
    if tx.is_reviewed:
        badge = Span(f"{category_name} ✓", cls="badge badge-success")
        status_text, status_color = "Complete", "text-success"
    else:
        badge = Span(category_name, cls="badge badge-saving")
        status_text, status_color = "Pending", "text-income"

    return Tr(
        Td(str(tx.date)),
        Td(
            str(tx.description),
            style="max-width: 24rem; overflow-wrap: anywhere; word-break: break-word;",
        ),
        Td(f"€{tx.amount:,.2f}", cls="amount-cell"),
        Td(badge),
        Td(
            Form(
                _category_select(tx, categories),
                Button("Save", type="submit", cls="btn btn-primary btn-sm"),
                Div("Saving...", id=f"loading-{tx.id}", cls="htmx-indicator text-secondary"),
                hx_put=f"/api/transactions/{tx.id}/categorize-htmx",
                hx_target=f"#transaction-{tx.id}",
                hx_swap="outerHTML",
                hx_indicator=f"#loading-{tx.id}",
                cls="inline-form",
            ),
            style="min-width: 18rem;",
        ),
        Td(status_text, cls=status_color),
        Td(confidence_display, cls=f"{_confidence_color(tx.confidence)} font-medium text-center"),
        id=f"transaction-{tx.id}",
    )


def render_row(tx, categories) -> str:
    """Render a single transaction row as an HTML fragment for HTMX swaps."""
    return to_xml(_row(tx, categories))


def render_table(transactions, categories, pagination_info=None) -> str:
    """Render the full transaction table, or an empty-state card if there is nothing to review."""
    if not transactions:
        empty = Div(
            P("No transactions to review at the moment.", cls="text-center text-secondary", style="padding: 2rem 0"),
            id="transaction-table",
            cls="card",
        )
        return to_xml(empty)

    table = Table(
        Thead(
            Tr(
                Th("Date"),
                Th("Description"),
                Th("Amount", style="text-align: right"),
                Th("Current Category"),
                Th("Categorize"),
                Th("Status"),
                Th("Confidence", style="text-align: center"),
            )
        ),
        Tbody(*[_row(tx, categories) for tx in transactions]),
    )

    children = [table]
    if pagination_info:
        children.append(
            create_full_pagination(
                pagination_info["page"], pagination_info["total_pages"], pagination_info["total_count"]
            )
        )

    return to_xml(Div(*children, id="transaction-table", cls="table-container"))
