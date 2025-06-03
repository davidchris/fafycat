"""Settings and categories page."""

from fastapi import Request

from web.components.layout import create_page_layout


def render_settings_page(request: Request):
    """Render the settings and categories page."""
    content = """
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-2xl font-bold mb-6">Settings & Categories</h1>

        <div class="mb-8">
            <h2 class="text-lg font-semibold mb-4">Manage Categories</h2>
            <div class="bg-white p-6 rounded-lg shadow mb-6">
                <h3 class="font-medium mb-3">Active Categories</h3>
                <p class="text-gray-600 mb-4">Category management interface will be implemented here.</p>
                <button class="bg-green-500 text-white px-4 py-2 rounded hover:bg-green-600">
                    Add New Category
                </button>
            </div>
        </div>

        <div class="mb-8">
            <h2 class="text-lg font-semibold mb-4">Export Settings</h2>
            <div class="bg-white p-6 rounded-lg shadow">
                <p class="text-gray-600 mb-4">Configure export options and download transaction data.</p>
                <button class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600">
                    Configure Export
                </button>
            </div>
        </div>
    </div>
    """

    return create_page_layout("Settings & Categories - FafyCat", content)
