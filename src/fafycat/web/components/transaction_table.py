"""Transaction table renderer shared by the review page and HTMX endpoints."""

from fasthtml.common import (
    A,
    Button,
    Div,
    Form,
    Input,
    NotStr,
    Option,
    P,
    Select,
    Span,
    Table,
    Tbody,
    Td,
    Th,
    Thead,
    Tr,
    to_xml,
)

from fafycat.web.components.pagination import FILTER_HX_INCLUDE, create_full_pagination

COLUMN_COUNT = 7
"""Columns in the transaction table; inline prompt rows span all of them."""


def _category_select(tx, categories) -> Select:
    """Category dropdown with the transaction's current category preselected."""
    current = tx.actual_category or tx.predicted_category
    # NotStr keeps the empty value attribute — fastcore drops falsy attr values,
    # and the placeholder must submit "" rather than its label text.
    options = [Option("Select category...", value=NotStr(""))]
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
            Div(str(tx.description)),
            A("trail", href=f"/transactions/{tx.id}/trail", cls="text-secondary text-sm", title="Why this category?"),
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
                # FastHTML defaults Form to multipart/form-data; keep the
                # urlencoded wire format the endpoint has always received.
                enctype="application/x-www-form-urlencoded",
                cls="inline-form",
            ),
            style="min-width: 18rem;",
        ),
        Td(status_text, cls=status_color),
        Td(confidence_display, cls=f"{_confidence_color(tx.confidence)} font-medium text-center"),
        id=f"transaction-{tx.id}",
    )


def _propagation_prompt(tx, pattern: str, sibling_count: int, category_name: str) -> Tr:
    """Build the inline row offering to apply a just-saved category to its siblings."""
    return Tr(
        Td(
            Span(
                f"{sibling_count} more unreviewed from {pattern}. ",
                cls="text-secondary",
            ),
            Form(
                Input(type="hidden", name="source_id", value=str(tx.id)),
                Input(type="hidden", name="actual_category", value=category_name),
                Button(f"Apply {category_name} to all", type="submit", cls="btn btn-primary btn-sm"),
                hx_post="/api/transactions/propagate",
                hx_target=f"#propagate-{tx.id}",
                hx_swap="outerHTML",
                enctype="application/x-www-form-urlencoded",
                cls="inline-form",
            ),
            Button(
                "Dismiss",
                cls="btn btn-sm",
                hx_get="/api/transactions/propagate/dismiss",
                hx_target=f"#propagate-{tx.id}",
                hx_swap="outerHTML",
            ),
            colspan=str(COLUMN_COUNT),
        ),
        id=f"propagate-{tx.id}",
        cls="propagation-prompt",
    )


def render_row(tx, categories) -> str:
    """Render a single transaction row as an HTML fragment for HTMX swaps."""
    return to_xml(_row(tx, categories))


def render_row_with_prompt(tx, categories, *, pattern: str, sibling_count: int, category_name: str) -> str:
    """Render a saved row followed by the prompt to propagate its category.

    Both rows are returned together because the categorize endpoint swaps the
    saved row by ``outerHTML``; a second ``<tr>`` with its own id rides along.

    Args:
        tx: The transaction that was just saved.
        categories: Categories offered in the row's dropdown.
        pattern: Cleaned merchant name the siblings share.
        sibling_count: Number of unreviewed siblings, always greater than zero.
        category_name: Category the user saved, offered for the siblings.
    """
    return to_xml(_row(tx, categories)) + to_xml(_propagation_prompt(tx, pattern, sibling_count, category_name))


def render_propagation_result(source_id: str, applied: int) -> str:
    """Render the one-line confirmation that replaces the propagation prompt."""
    return to_xml(
        Tr(
            Td(
                f"Applied to {applied} transaction{'' if applied == 1 else 's'}",
                cls="text-success",
                colspan=str(COLUMN_COUNT),
            ),
            id=f"propagate-{source_id}",
        )
    )


def _container(*children, cls: str, page: int = 1) -> Div:
    """Wrap the table in the container that reloads itself on ``transactions-changed``.

    A propagation reviews rows the user never touched, so the table has to
    re-fetch. The current page and the full filter set ride along, otherwise
    the refresh would silently reset what the user is looking at (see #48).

    Args:
        *children: Contents of the container.
        cls: CSS classes for the container.
        page: Page to re-fetch when the event fires.
    """
    return Div(
        *children,
        id="transaction-table",
        cls=cls,
        hx_get=f"/api/transactions/table?page={page}",
        hx_trigger="transactions-changed from:body",
        hx_target="#transaction-table",
        hx_swap="outerHTML",
        hx_include=FILTER_HX_INCLUDE,
    )


def render_table(transactions, categories, pagination_info=None) -> str:
    """Render the full transaction table, or an empty-state card if there is nothing to review."""
    if not transactions:
        # Nothing on this page any more, so a refresh starts over at page 1.
        empty = _container(
            P("No transactions to review at the moment.", cls="text-center text-secondary", style="padding: 2rem 0"),
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
                pagination_info["page"],
                pagination_info["total_pages"],
                pagination_info["total_count"],
                per_page=pagination_info.get("page_size", 50),
            )
        )

    page = pagination_info["page"] if pagination_info else 1
    return to_xml(_container(*children, cls="table-container", page=page))
