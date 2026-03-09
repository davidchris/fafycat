"""Home page — Bauhaus gateway to the FafyCat workflow."""

from web.components.icons import icon_analytics, icon_cat_brand, icon_export, icon_import, icon_review, icon_settings


def render_home_page() -> str:
    """Render the home page with brand hero and workflow navigation cards."""
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
            "/review", "Review", "Categorize transactions", icon_review(28), "--color-income", "badge-income", "2"
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
    href: str, title: str, description: str, icon: str, color_var: str, badge_class: str, step: str
) -> str:
    """Render a single workflow navigation card."""
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
            </div>
            <span class="badge {badge_class}">{step}</span>
        </div>
    </a>
    """
