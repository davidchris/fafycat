"""Home page — Bauhaus gateway to the FafyCat workflow."""

import html

from fafycat.web.components.icons import (
    icon_analytics,
    icon_cat_brand,
    icon_export,
    icon_import,
    icon_review,
    icon_settings,
)


def render_home_page(unreviewed_this_month: int = 0) -> str:
    """Render the home page with brand hero and workflow navigation cards.

    Args:
        unreviewed_this_month: Number of unreviewed transactions dated in the current calendar
            month. Shown on the Review card when greater than zero.

    Returns:
        HTML string for the home page body.
    """
    review_note = f"{unreviewed_this_month} unreviewed this month" if unreviewed_this_month > 0 else ""
    return f"""
    <div style="max-width: 960px;" class="container mx-auto px-4">

        <!-- Hero — Brand Identity -->
        <div class="hero-section">
            <div class="hero-icon-wrapper">
                {icon_cat_brand(80)}
            </div>
            <h1 class="hero-title">
                FAFYCAT
            </h1>
            <p class="hero-subtitle text-secondary">
                Family Finance Categorizer
            </p>
            <div class="hero-divider"></div>
        </div>

        <!-- Workflow Pipeline — 4 Navigation Cards -->
        <div class="workflow-grid">
            {
        _workflow_card(
            "/import", "Import", "Upload bank CSV files", icon_import(28), "--color-saving", "badge-saving", "1"
        )
    }
            {
        _workflow_card(
            "/review",
            "Review",
            "Categorize transactions",
            icon_review(28),
            "--color-income",
            "badge-income",
            "2",
            note=review_note,
        )
    }
            {
        _workflow_card(
            "/analytics",
            "Analytics",
            "Charts and insights",
            icon_analytics(28),
            "--color-spending",
            "badge-spending",
            "3",
        )
    }
            {
        _workflow_card(
            "/export", "Export", "Download your data", icon_export(28), "--color-success", "badge-success", "4"
        )
    }
        </div>

        <!-- Footer — Settings Quick Access -->
        <div class="footer-nav">
            <a href="/settings" class="btn-ghost footer-link">
                {icon_settings(16)}
                Settings &amp; ML Configuration
            </a>
        </div>
    </div>
    """


def _workflow_card(
    href: str,
    title: str,
    description: str,
    icon: str,
    color_var: str,
    badge_class: str,
    step: str,
    note: str = "",
) -> str:
    """Render a single workflow navigation card.

    Args:
        href: Target route of the card.
        title: Card headline.
        description: Short explanation below the headline.
        icon: Inline SVG markup for the card icon.
        color_var: CSS custom property name used as the accent colour.
        badge_class: CSS class of the step badge.
        step: Step number shown in the badge.
        note: Optional muted status line; omitted when empty.

    Returns:
        HTML string for one workflow card.
    """
    note_html = f'<div class="workflow-card-note text-secondary text-sm">{html.escape(note)}</div>' if note else ""
    return f"""
    <a href="{href}" class="card workflow-card" style="--card-color: var({color_var});">
        <div class="workflow-card-inner">
            <div class="workflow-card-icon">{icon}</div>
            <div class="workflow-card-content">
                <div class="workflow-card-title">
                    {title}
                </div>
                <div class="workflow-card-desc">
                    {description}
                </div>
                {note_html}
            </div>
            <span class="badge {badge_class}">{step}</span>
        </div>
    </a>
    """
