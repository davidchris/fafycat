"""Layout components for web pages — Bauhaus dark mode."""

from fafycat.web.components.icons import (
    icon_analytics,
    icon_cat_brand,
    icon_export,
    icon_hamburger,
    icon_import,
    icon_review,
    icon_settings,
)


def create_sidebar() -> str:
    """Create the navigation sidebar HTML."""
    return f"""
    <!-- Mobile hamburger -->
    <button class="hamburger-btn"
            id="hamburger-btn"
            aria-label="Menu"
            aria-controls="sidebar"
            aria-expanded="false">
        {icon_hamburger()}
    </button>

    <!-- Backdrop -->
    <div id="sidebar-backdrop" class="sidebar-backdrop" aria-hidden="true"></div>

    <!-- Sidebar -->
    <aside id="sidebar" class="sidebar">
        <div class="sidebar-brand">
            <div class="flex items-center gap-2">
                {icon_cat_brand(28)}
                <span class="sidebar-brand-name">FAFYCAT</span>
            </div>
        </div>

        <nav class="sidebar-nav">
            <a href="/import" class="sidebar-link" data-path="/import">
                {icon_import()}
                <span>Import</span>
            </a>
            <a href="/review" class="sidebar-link" data-path="/review">
                {icon_review()}
                <span>Review</span>
            </a>
            <a href="/analytics" class="sidebar-link" data-path="/analytics">
                {icon_analytics()}
                <span>Analytics</span>
            </a>
            <a href="/export" class="sidebar-link" data-path="/export">
                {icon_export()}
                <span>Export</span>
            </a>
            <a href="/settings" class="sidebar-link" data-path="/settings">
                {icon_settings()}
                <span>Settings</span>
            </a>
        </nav>
    </aside>
    """


def create_page_layout(title: str, content: str) -> str:
    """Create the main page layout with sidebar and content area."""
    return f"""
    <!DOCTYPE html>
    <html lang="en" class="no-js">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta name="color-scheme" content="dark">
        <title>{title}</title>
        <link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
        <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
        <link href="/static/css/theme.css" rel="stylesheet">
        <link href="/static/css/components.css" rel="stylesheet">
        <script>document.documentElement.className='js-enabled';</script>
        <script src="https://unpkg.com/htmx.org@1.9.12"></script>
        <script src="/static/js/main.js" defer></script>
    </head>
    <body class="antialiased">
        {create_sidebar()}
        <div class="main-content lg:ml-56 min-h-screen">
            <main class="max-w-7xl mx-auto px-6 py-8">
                {content}
            </main>
        </div>
    </body>
    </html>
    """
