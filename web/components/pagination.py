"""Pagination components using FastHTML."""

from fasthtml.common import Button, Div, Nav, P, Span


def create_pagination_info(page: int, total_count: int, per_page: int = 50) -> Div:
    """Create pagination info display."""
    start_item = (page - 1) * per_page + 1
    end_item = min(page * per_page, total_count)

    return P(
        "Showing ",
        Span(str(start_item), cls="font-medium"),
        " to ",
        Span(str(end_item), cls="font-medium"),
        " of ",
        Span(str(total_count), cls="font-medium"),
        " results",
        cls="text-sm text-gray-700",
    )


def create_pagination_button(
    page: int, text: str, is_disabled: bool, htmx_attrs: dict[str, str], additional_classes: str = ""
) -> Button:
    """Create a pagination button with HTMX attributes."""
    base_classes = (
        "relative inline-flex items-center px-2 py-2 border border-gray-300 "
        "bg-white text-sm font-medium text-gray-500 hover:bg-gray-50"
    )

    cls = f"{base_classes} {additional_classes}".strip()

    if is_disabled:
        cls += " cursor-not-allowed opacity-50"
        return Button(text, disabled=True, cls=cls)

    return Button(
        text,
        cls=cls,
        hx_get=htmx_attrs.get("hx_get"),
        hx_target=htmx_attrs.get("hx_target"),
        hx_include=htmx_attrs.get("hx_include"),
    )


def create_mobile_pagination(page: int, total_pages: int, has_prev: bool, has_next: bool) -> Div:
    """Create mobile-friendly pagination (Previous/Next only)."""
    htmx_include = "[name='status']:checked, [name='confidence_lt'], [name='search']"

    prev_button = create_pagination_button(
        page - 1 if has_prev else 1,
        "Previous",
        not has_prev,
        {
            "hx_get": f"/api/transactions/table?page={page - 1 if has_prev else 1}",
            "hx_target": "#transaction-table",
            "hx_include": htmx_include,
        },
        "rounded-md px-4",
    )

    next_button = create_pagination_button(
        page + 1 if has_next else total_pages,
        "Next",
        not has_next,
        {
            "hx_get": f"/api/transactions/table?page={page + 1 if has_next else total_pages}",
            "hx_target": "#transaction-table",
            "hx_include": htmx_include,
        },
        "ml-3 rounded-md px-4",
    )

    return Div(prev_button, next_button, cls="flex-1 flex justify-between sm:hidden")


def create_desktop_pagination(page: int, total_pages: int, has_prev: bool, has_next: bool) -> Nav:
    """Create full desktop pagination with First/Prev/Next/Last buttons."""
    htmx_include = "[name='status']:checked, [name='confidence_lt'], [name='search']"

    # First button
    first_button = create_pagination_button(
        1,
        "‹‹ First",
        not has_prev,
        {"hx_get": "/api/transactions/table?page=1", "hx_target": "#transaction-table", "hx_include": htmx_include},
        "rounded-l-md",
    )

    # Previous button
    prev_button = create_pagination_button(
        page - 1 if has_prev else 1,
        "‹ Prev",
        not has_prev,
        {
            "hx_get": f"/api/transactions/table?page={page - 1 if has_prev else 1}",
            "hx_target": "#transaction-table",
            "hx_include": htmx_include,
        },
    )

    # Page indicator
    page_indicator = Span(
        f"Page {page} of {total_pages}",
        cls=(
            "relative inline-flex items-center px-4 py-2 border border-gray-300 "
            "bg-white text-sm font-medium text-gray-700"
        ),
    )

    # Next button
    next_button = create_pagination_button(
        page + 1 if has_next else total_pages,
        "Next ›",
        not has_next,
        {
            "hx_get": f"/api/transactions/table?page={page + 1 if has_next else total_pages}",
            "hx_target": "#transaction-table",
            "hx_include": htmx_include,
        },
    )

    # Last button
    last_button = create_pagination_button(
        total_pages,
        "Last ››",
        not has_next,
        {
            "hx_get": f"/api/transactions/table?page={total_pages}",
            "hx_target": "#transaction-table",
            "hx_include": htmx_include,
        },
        "rounded-r-md",
    )

    return Nav(
        first_button,
        prev_button,
        page_indicator,
        next_button,
        last_button,
        cls="relative z-0 inline-flex rounded-md shadow-sm -space-x-px",
        aria_label="Pagination",
    )


def create_full_pagination(page: int, total_pages: int, total_count: int, per_page: int = 50) -> Div:
    """Create complete pagination component with mobile and desktop versions."""
    has_prev = page > 1
    has_next = page < total_pages

    mobile_pagination = create_mobile_pagination(page, total_pages, has_prev, has_next)

    pagination_info = create_pagination_info(page, total_count, per_page)
    desktop_pagination = create_desktop_pagination(page, total_pages, has_prev, has_next)

    desktop_section = Div(
        Div(pagination_info), Div(desktop_pagination), cls="hidden sm:flex-1 sm:flex sm:items-center sm:justify-between"
    )

    return Div(
        Div(mobile_pagination, desktop_section, cls="flex items-center justify-between"),
        cls="bg-white px-4 py-3 border-t border-gray-200 sm:px-6",
    )
