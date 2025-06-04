"""Review and categorize transactions page."""

from fastapi import Request

from api.dependencies import get_db_manager
from api.services import CategoryService, TransactionService
from web.components.layout import create_page_layout


def _generate_transaction_table(transactions, categories):
    """Generate HTML table for transactions."""
    if not transactions:
        return """
        <div class="bg-white rounded-lg shadow p-6">
            <p class="text-center text-gray-500 py-8">No transactions to review at the moment.</p>
        </div>
        """

    # Generate table rows
    table_rows = ""
    for tx in transactions:
        confidence_color = (
            "text-red-600"
            if tx.confidence and tx.confidence < 0.5
            else "text-yellow-600"
            if tx.confidence and tx.confidence < 0.8
            else "text-green-600"
        )
        confidence_display = f"{tx.confidence:.1%}" if tx.confidence else "N/A"

        # Generate category options with current category selected
        current_category = tx.actual_category or tx.predicted_category
        category_options = '<option value="">Select category...</option>'
        for cat in categories:
            selected = ' selected' if cat.name == current_category else ''
            category_options += f'<option value="{cat.name}"{selected}>{cat.name}</option>'

        table_rows += f"""
        <tr class="border-b hover:bg-gray-50">
            <td class="px-4 py-3 text-sm">{tx.date}</td>
            <td class="px-4 py-3 text-sm font-medium">{tx.description}</td>
            <td class="px-4 py-3 text-sm text-right">${tx.amount:,.2f}</td>
            <td class="px-4 py-3 text-sm">
                <span class="px-2 py-1 bg-blue-100 text-blue-800 rounded text-xs">
                    {tx.actual_category or tx.predicted_category or "Uncategorized"}
                </span>
            </td>
            <td class="px-4 py-3 text-sm {confidence_color} font-medium">{confidence_display}</td>
            <td class="px-4 py-3 text-sm">
                <form method="post" action="/transactions/{tx.id}/categorize" class="flex gap-2">
                    <select name="actual_category" class="text-sm border border-gray-300 rounded px-2 py-1">
                        {category_options}
                    </select>
                    <button type="submit" class="px-3 py-1 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">
                        Save
                    </button>
                </form>
            </td>
        </tr>
        """

    return f"""
    <div class="bg-white rounded-lg shadow overflow-hidden">
        <table class="min-w-full divide-y divide-gray-200">
            <thead class="bg-gray-50">
                <tr>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Date</th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Description</th>
                    <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Amount</th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Predicted</th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Confidence</th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Categorize</th>
                </tr>
            </thead>
            <tbody class="bg-white divide-y divide-gray-200">
                {table_rows}
            </tbody>
        </table>
    </div>
    """


def render_review_page(request: Request):
    """Render the review and categorize transactions page."""
    db_manager = get_db_manager(request)

    try:
        with db_manager.get_session() as session:
            # Fetch pending transactions and categories
            transactions = TransactionService.get_pending_transactions(session, limit=50)
            categories = CategoryService.get_categories(session)

            # Generate transaction table
            transactions_html = _generate_transaction_table(transactions, categories)

            transaction_count = len(transactions)

    except Exception as e:
        # Fallback in case of database error
        transactions_html = f"""
        <div class="bg-red-50 border border-red-200 rounded-lg p-4">
            <p class="text-red-800">Error loading transactions: {str(e)}</p>
        </div>
        """
        transaction_count = 0

    content = f"""
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-2xl font-bold mb-6">Review & Categorize</h1>

        <div class="mb-8">
            <h2 class="text-lg font-semibold mb-4">Pending Review ({transaction_count} transactions)</h2>
            <p class="text-gray-600 mb-4">Transactions requiring manual review and categorization.</p>
            {transactions_html}
        </div>

        <div class="mb-8">
            <h2 class="text-lg font-semibold mb-4">Filters</h2>
            <div class="bg-gray-50 p-4 rounded">
                <label class="block text-sm font-medium mb-2">Confidence threshold:</label>
                <input type="range" min="0" max="1" step="0.1" value="0.5" class="w-full">
                <p class="text-sm text-gray-600 mt-2">Show transactions with confidence below 50%</p>
            </div>
        </div>
    </div>
    """

    return create_page_layout("Review & Categorize - FafyCat", content)
