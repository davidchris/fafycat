"""Button components using FastHTML."""

from fasthtml.common import A


def create_action_button(text: str, url: str, color: str = "blue") -> A:
    """Create a styled action button."""
    color_classes = {
        "blue": "bg-blue-500 text-white hover:bg-blue-600",
        "green": "bg-green-500 text-white hover:bg-green-600",
        "gray": "bg-gray-500 text-white hover:bg-gray-600",
    }

    button_class = f"{color_classes.get(color, color_classes['blue'])} px-4 py-2 rounded"

    return A(text, href=url, cls=button_class)


def create_button_group(*buttons) -> A:
    """Create a group of buttons with spacing."""
    from fasthtml.common import Div

    return Div(*buttons, cls="flex gap-4")
