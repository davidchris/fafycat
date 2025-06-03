"""Import transactions page."""

from fastapi import Request

from web.components.layout import create_page_layout


def render_import_page(request: Request):
    """Render the import transactions page."""
    content = """
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-2xl font-bold mb-6">Import Transactions</h1>

        <div class="mb-8">
            <h2 class="text-lg font-semibold mb-4">Upload CSV File</h2>
            <form action="/upload-csv" method="post" enctype="multipart/form-data"
                  class="bg-white p-6 rounded-lg shadow">
                <div class="mb-4">
                    <label class="block text-sm font-medium mb-2">Select CSV file:</label>
                    <input type="file" name="file" accept=".csv" class="block w-full border rounded p-2">
                </div>
                <button type="submit" class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600">
                    Upload and Preview
                </button>
            </form>
        </div>

        <div class="bg-gray-50 p-6 rounded-lg">
            <h2 class="text-lg font-semibold mb-4">Import Instructions</h2>
            <ul class="list-disc list-inside space-y-2 text-gray-700">
                <li>CSV should contain columns: Date, Description, Amount, Account</li>
                <li>Date format should be YYYY-MM-DD or MM/DD/YYYY</li>
                <li>Amount should be numeric (negative for expenses, positive for income)</li>
                <li>Duplicate transactions will be automatically skipped</li>
            </ul>
        </div>
    </div>
    """

    return create_page_layout("Import Transactions - FafyCat", content)
