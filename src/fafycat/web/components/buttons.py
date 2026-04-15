"""Button components using FastHTML."""

from typing import Any

from fasthtml.common import A


def create_action_button(text: str, url: str, color: str = "blue") -> A:
    """Create a styled action button."""
    color_classes = {
        "blue": "btn btn-primary",
        "green": "btn btn-success",
        "gray": "btn btn-secondary",
    }

    button_class = color_classes.get(color, color_classes["blue"])

    return A(text, href=url, cls=button_class)


def create_button_group(*buttons: Any) -> Any:
    """Create a group of buttons with spacing."""
    from fasthtml.common import Div

    return Div(*buttons, cls="flex gap-4")
