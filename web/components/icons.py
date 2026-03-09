"""Geometric SVG icons for FafyCat - Bauhaus-inspired functional marks."""

_STROKE = 'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"'
_STROKE2 = 'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'


def _svg(size: int, viewbox: str, attrs: str, body: str) -> str:
    """Build an SVG element with common attributes."""
    return f'<svg width="{size}" height="{size}" viewBox="{viewbox}" {attrs}>{body}</svg>'


def icon_cat_brand(size: int = 24) -> str:
    """Cat brand mark: two triangles (ears) + circle (head)."""
    return _svg(
        size,
        "0 0 24 24",
        'fill="none"',
        '<polygon points="4,14 8,4 12,14" fill="#F5C518"/>'
        '<polygon points="12,14 16,4 20,14" fill="#F5C518"/>'
        '<circle cx="12" cy="16" r="6" fill="#F0F0F0"/>',
    )


def icon_import(size: int = 18) -> str:
    """Upload/import: arrow pointing into a box."""
    return _svg(
        size,
        "0 0 18 18",
        f'fill="none" {_STROKE}',
        '<path d="M9 2v9"/><path d="M5 7l4 4 4-4"/><path d="M2 12v3a1 1 0 001 1h12a1 1 0 001-1v-3"/>',
    )


def icon_review(size: int = 18) -> str:
    """Review: checkmark in circle."""
    return _svg(
        size,
        "0 0 18 18",
        f'fill="none" {_STROKE}',
        '<circle cx="9" cy="9" r="7"/><path d="M6 9l2 2 4-4"/>',
    )


def icon_analytics(size: int = 18) -> str:
    """Analytics: three ascending bars."""
    return _svg(
        size,
        "0 0 18 18",
        'fill="currentColor"',
        '<rect x="2" y="10" width="3" height="6" rx="0.5"/>'
        '<rect x="7.5" y="6" width="3" height="10" rx="0.5"/>'
        '<rect x="13" y="2" width="3" height="14" rx="0.5"/>',
    )


def icon_export(size: int = 18) -> str:
    """Export: arrow leaving a box."""
    return _svg(
        size,
        "0 0 18 18",
        f'fill="none" {_STROKE}',
        '<path d="M9 11V2"/><path d="M5 6l4-4 4 4"/><path d="M2 12v3a1 1 0 001 1h12a1 1 0 001-1v-3"/>',
    )


def icon_settings(size: int = 18) -> str:
    """Settings: gear/cog."""
    return _svg(
        size,
        "0 0 18 18",
        f'fill="none" {_STROKE}',
        '<circle cx="9" cy="9" r="2.5"/>'
        '<path d="M9 1.5v2M9 14.5v2M1.5 9h2M14.5 9h2'
        "M3.1 3.1l1.4 1.4M13.5 13.5l1.4 1.4"
        'M3.1 14.9l1.4-1.4M13.5 4.5l1.4-1.4"/>',
    )


def icon_spending(size: int = 18) -> str:
    """Spending: downward arrow (red context)."""
    return _svg(
        size,
        "0 0 18 18",
        f'fill="none" {_STROKE}',
        '<path d="M9 3v12"/><path d="M5 11l4 4 4-4"/>',
    )


def icon_income(size: int = 18) -> str:
    """Income: upward arrow (yellow context)."""
    return _svg(
        size,
        "0 0 18 18",
        f'fill="none" {_STROKE}',
        '<path d="M9 15V3"/><path d="M5 7l4-4 4 4"/>',
    )


def icon_saving(size: int = 18) -> str:
    """Saving: shield/vault (blue context)."""
    return _svg(
        size,
        "0 0 18 18",
        f'fill="none" {_STROKE}',
        '<path d="M9 2L3 5v4c0 4 2.7 6.4 6 8 3.3-1.6 6-4 6-8V5L9 2z"/>',
    )


def icon_success(size: int = 18) -> str:
    """Success: checkmark."""
    return _svg(
        size,
        "0 0 18 18",
        f'fill="none" {_STROKE2}',
        '<path d="M4 9l3.5 3.5L14 5"/>',
    )


def icon_warning(size: int = 18) -> str:
    """Warning: triangle."""
    return _svg(
        size,
        "0 0 18 18",
        f'fill="none" {_STROKE}',
        '<path d="M9 2L1 16h16L9 2z"/><path d="M9 7v4"/><circle cx="9" cy="13" r="0.5" fill="currentColor"/>',
    )


def icon_error(size: int = 18) -> str:
    """Error: X in circle."""
    return _svg(
        size,
        "0 0 18 18",
        f'fill="none" {_STROKE}',
        '<circle cx="9" cy="9" r="7"/><path d="M6.5 6.5l5 5M11.5 6.5l-5 5"/>',
    )


def icon_info(size: int = 18) -> str:
    """Info: i in circle."""
    return _svg(
        size,
        "0 0 18 18",
        f'fill="none" {_STROKE}',
        '<circle cx="9" cy="9" r="7"/><path d="M9 8v5"/><circle cx="9" cy="5.5" r="0.5" fill="currentColor"/>',
    )


def icon_ml(size: int = 18) -> str:
    """ML/AI: neural network nodes."""
    return _svg(
        size,
        "0 0 18 18",
        'fill="currentColor"',
        '<circle cx="3" cy="5" r="1.5"/><circle cx="3" cy="13" r="1.5"/>'
        '<circle cx="9" cy="4" r="1.5"/><circle cx="9" cy="9" r="1.5"/>'
        '<circle cx="9" cy="14" r="1.5"/><circle cx="15" cy="9" r="1.5"/>',
    )


def icon_hamburger(size: int = 20) -> str:
    """Hamburger menu: three horizontal lines."""
    return _svg(
        size,
        "0 0 20 20",
        'fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"',
        '<path d="M3 5h14M3 10h14M3 15h14"/>',
    )


def icon_close(size: int = 18) -> str:
    """Close: X mark."""
    return _svg(
        size,
        "0 0 18 18",
        'fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"',
        '<path d="M4 4l10 10M14 4L4 14"/>',
    )
