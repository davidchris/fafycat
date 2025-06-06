"""Alert and notification components using FastHTML."""

from fasthtml.common import H3, A, Div, P


def create_success_alert(title: str, message: str, details: dict = None) -> Div:
    """Create a green success alert box."""
    content = [H3(title, cls="text-lg font-semibold text-green-800 mb-2")]

    if details:
        detail_items = []
        for key, value in details.items():
            detail_items.append(P(f"{key}: {value}"))
        content.extend(detail_items)

    if message:
        content.append(P(message, cls="text-green-700"))

    return Div(*content, cls="bg-green-50 border border-green-200 rounded-lg p-6 mb-6")


def create_info_alert(title: str, message: str, link_text: str = None, link_url: str = None) -> Div:
    """Create a blue info alert box."""
    content = [H3(title, cls="text-lg font-semibold text-blue-800 mb-2")]

    if link_text and link_url:
        message_with_link = P(
            message, " ", A(link_text, href=link_url, cls="underline hover:text-blue-600"), ".", cls="text-blue-700"
        )
        content.append(message_with_link)
    else:
        content.append(P(message, cls="text-blue-700"))

    return Div(*content, cls="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6")


def create_purple_alert(title: str, message: str) -> Div:
    """Create a purple ML/prediction alert box."""
    return Div(
        H3(title, cls="text-lg font-semibold text-purple-800 mb-2"),
        P(message, cls="text-purple-700"),
        cls="bg-purple-50 border border-purple-200 rounded-lg p-4 mb-6",
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
