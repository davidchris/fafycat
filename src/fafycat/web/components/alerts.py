"""Alert and notification components using FastHTML."""

from fasthtml.common import H3, A, Div, P


def create_success_alert(title: str, message: str, details: dict | None = None) -> Div:
    """Create a success alert box."""
    content = [H3(title, cls="alert-title")]

    if details:
        detail_items = []
        for key, value in details.items():
            detail_items.append(P(f"{key}: {value}"))
        content.extend(detail_items)

    if message:
        content.append(P(message))

    return Div(*content, cls="alert alert-success")


def create_info_alert(title: str, message: str, link_text: str | None = None, link_url: str | None = None) -> Div:
    """Create an info alert box."""
    content = [H3(title, cls="alert-title")]

    if link_text and link_url:
        message_with_link = P(message, " ", A(link_text, href=link_url, cls="underline"), ".")
        content.append(message_with_link)
    else:
        content.append(P(message))

    return Div(*content, cls="alert alert-info")


def create_purple_alert(title: str, message: str) -> Div:
    """Create a purple ML/prediction alert box."""
    return Div(
        H3(title, cls="alert-title"),
        P(message),
        cls="alert alert-ml",
    )


def create_upload_result_alert(
    success_msg: str, filename: str, rows_processed: int, new_count: int, duplicate_count: int
) -> Div:
    """Create upload results alert with structured data."""
    details = {
        "File": filename,
        "Rows processed": rows_processed,
        "New transactions": new_count,
        "Duplicates skipped": duplicate_count,
    }

    return create_success_alert(success_msg, "", details)
