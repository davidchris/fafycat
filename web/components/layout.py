"""Layout components for web pages."""


def create_sidebar():
    """Create the navigation sidebar HTML."""
    return """
    <div class="w-64 bg-gray-50 h-screen p-4 fixed left-0 top-0 flex flex-col">
        <div class="mb-6">
            <h2 class="text-xl font-bold mb-2">🐱 FafyCat</h2>
            <p class="text-sm text-gray-600 mb-4">Family Finance Categorizer</p>
        </div>
        <nav class="mb-6">
            <ul class="space-y-1">
                <li><a href="/import" class="block py-2 px-3 rounded hover:bg-gray-100">Import Transactions</a></li>
                <li><a href="/review" class="block py-2 px-3 rounded hover:bg-gray-100">Review & Categorize</a></li>
                <li><a href="/settings" class="block py-2 px-3 rounded hover:bg-gray-100">Settings & Categories</a></li>
            </ul>
        </nav>
        <hr class="mb-4">
        <div class="mt-auto">
            <p class="text-xs text-gray-500 mb-1">Built with ❤️ using FastAPI + FastHTML</p>
            <p class="text-xs text-gray-500">Local-first • Privacy-focused • ML-powered</p>
        </div>
    </div>
    """


def create_page_layout(title: str, content: str):
    """Create the main page layout with sidebar and content area."""
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{title}</title>
        <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
        <link href="/static/css/main.css" rel="stylesheet">
    </head>
    <body>
        {create_sidebar()}
        <div class="ml-64 min-h-screen">
            {content}
        </div>
        <script src="/static/js/main.js"></script>
    </body>
    </html>
    """
