"""Review and categorize transactions page."""

from fastapi import Request

from api.dependencies import get_db_manager
from api.services import CategoryService, TransactionService
from web.components.layout import create_page_layout


def _get_model_status_alert():
    """Get model status and return HTML alert if model needs training."""
    try:
        # Get ML status directly without HTTP call
        from src.fafycat.core.config import AppConfig
        from src.fafycat.core.database import DatabaseManager, TransactionORM

        config = AppConfig()
        db_manager = DatabaseManager(config)

        with db_manager.get_session() as db_session:
            model_path = config.ml.model_dir / "categorizer.pkl"

            # Check training data readiness
            reviewed_count = (
                db_session.query(TransactionORM)
                .filter(TransactionORM.is_reviewed, TransactionORM.category_id.is_not(None))
                .count()
            )

            min_training_samples = 50
            training_ready = reviewed_count >= min_training_samples

            # Check unpredicted transactions
            unpredicted_count = (
                db_session.query(TransactionORM).filter(TransactionORM.predicted_category_id.is_(None)).count()
            )

            if model_path.exists():
                status = {
                    "model_loaded": True,
                    "can_predict": True,
                    "training_ready": training_ready,
                    "reviewed_transactions": reviewed_count,
                    "unpredicted_transactions": unpredicted_count,
                }
            else:
                status = {
                    "model_loaded": False,
                    "can_predict": False,
                    "training_ready": training_ready,
                    "reviewed_transactions": reviewed_count,
                    "unpredicted_transactions": unpredicted_count,
                }

            # If model is loaded and working, no alert needed
            if status.get("model_loaded", False) and status.get("can_predict", False):
                return ""

            # Show training ready alert
            if status.get("training_ready", False):
                reviewed_count = status.get("reviewed_transactions", 0)
                unpredicted_count = status.get("unpredicted_transactions", 0)

                return f"""
                <div class="mb-6 bg-blue-50 border border-blue-200 rounded-lg p-4">
                    <div class="flex items-start">
                        <div class="flex-shrink-0">
                            <svg class="h-5 w-5 text-blue-400" viewBox="0 0 20 20" fill="currentColor">
                                <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd" />
                            </svg>
                        </div>
                        <div class="ml-3 flex-1">
                            <h3 class="text-sm font-medium text-blue-800">
                                Ready to train ML model
                            </h3>
                            <div class="mt-2 text-sm text-blue-700">
                                <p>You have {reviewed_count} reviewed transactions ready for training. 
                                {unpredicted_count} transactions are missing predictions.</p>
                            </div>
                            <div class="mt-4">
                                <a href="/settings" 
                                   class="inline-flex items-center px-3 py-2 text-sm font-medium text-blue-600 bg-blue-100 rounded-md hover:bg-blue-200">
                                    Train Model Now
                                </a>
                            </div>
                        </div>
                        <div class="ml-auto">
                            <button type="button" 
                                    onclick="this.parentElement.parentElement.parentElement.style.display='none'"
                                    class="text-blue-400 hover:text-blue-600">
                                <svg class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                                    <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
                                </svg>
                            </button>
                        </div>
                    </div>
                </div>
                """

            # Show not enough data alert
            reviewed_count = status.get("reviewed_transactions", 0)
            min_required = status.get("min_training_samples", 50)

            return f"""
                <div class="mb-6 bg-yellow-50 border border-yellow-200 rounded-lg p-4">
                    <div class="flex items-start">
                        <div class="flex-shrink-0">
                            <svg class="h-5 w-5 text-yellow-400" viewBox="0 0 20 20" fill="currentColor">
                                <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
                            </svg>
                        </div>
                        <div class="ml-3">
                            <h3 class="text-sm font-medium text-yellow-800">
                                More training data needed
                            </h3>
                            <div class="mt-2 text-sm text-yellow-700">
                                <p>You have {reviewed_count} reviewed transactions. Need at least {min_required} for training a model.</p>
                            </div>
                        </div>
                    </div>
                </div>
                """

    except Exception:
        # If we can't get status, don't show alert (fail silently)
        pass

    return ""


def _generate_category_options(categories):
    """Generate category options for the filter dropdown."""
    options = ""
    for cat in categories:
        options += f'<option value="{cat.name}">{cat.name}</option>'
    return options


def _generate_transaction_table(transactions, categories):
    """Generate HTML table for transactions with HTMX enhancements."""
    if not transactions:
        return """
        <div id="transaction-table" class="bg-white rounded-lg shadow p-6">
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
            selected = " selected" if cat.name == current_category else ""
            category_options += f'<option value="{cat.name}"{selected}>{cat.name}</option>'

        # Status display
        status_color = "text-green-600" if tx.is_reviewed else "text-yellow-600"
        status_text = "Complete" if tx.is_reviewed else "Pending"

        table_rows += f"""
        <tr id="transaction-{tx.id}" class="border-b hover:bg-gray-50">
            <td class="px-4 py-3 text-sm">{tx.date}</td>
            <td class="px-4 py-3 text-sm font-medium">{tx.description}</td>
            <td class="px-4 py-3 text-sm text-right">${tx.amount:,.2f}</td>
            <td class="px-4 py-3 text-sm">
                <span class="px-2 py-1 bg-blue-100 text-blue-800 rounded text-xs">
                    {tx.actual_category or tx.predicted_category or "Uncategorized"}
                </span>
            </td>
            <td class="px-4 py-3 text-sm">
                <form hx-put="/api/transactions/{tx.id}/categorize-htmx"
                      hx-target="#transaction-{tx.id}"
                      hx-swap="outerHTML"
                      hx-indicator="#loading-{tx.id}"
                      class="flex gap-2 items-center">
                    <select name="actual_category" class="text-sm border border-gray-300 rounded px-2 py-1">
                        {category_options}
                    </select>
                    <button type="submit" class="px-3 py-1 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">
                        Save
                    </button>
                    <div id="loading-{tx.id}" class="htmx-indicator text-xs text-gray-500">
                        Saving...
                    </div>
                </form>
            </td>
            <td class="px-4 py-3 text-sm {status_color}">{status_text}</td>
            <td class="px-4 py-3 text-sm {confidence_color} font-medium text-center">{confidence_display}</td>
        </tr>
        """

    return f"""
    <div id="transaction-table" class="bg-white rounded-lg shadow overflow-hidden">
        <table class="min-w-full divide-y divide-gray-200">
            <thead class="bg-gray-50">
                <tr>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Date</th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Description</th>
                    <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Amount</th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Current Category</th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Categorize</th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Status</th>
                    <th class="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Confidence</th>
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
            # Use the new paginated service to get initial transaction data (default to high priority)
            result = TransactionService.get_transactions_with_pagination(
                session=session,
                skip=0,
                limit=50,
                is_reviewed=False,  # Default to pending
                review_priority="high_priority",  # Default to high priority transactions
                confidence_lt=0.8,  # Default confidence threshold
                sort_by="date",
                sort_order="desc",
                search="",
            )

            categories = CategoryService.get_categories(session)

            # Generate transaction table with pagination
            from api.transactions import _generate_transaction_table_htmx

            transactions_html = _generate_transaction_table_htmx(
                result["transactions"], categories, result["pagination_info"]
            )

            transaction_count = result["pagination_info"]["total_count"]

    except Exception as e:
        # Fallback in case of database error
        transactions_html = f"""
        <div class="bg-red-50 border border-red-200 rounded-lg p-4">
            <p class="text-red-800">Error loading transactions: {str(e)}</p>
        </div>
        """
        transaction_count = 0

    # Get model status alert
    model_alert = _get_model_status_alert()

    content = f"""
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-2xl font-bold mb-6">Review & Categorize</h1>

        {model_alert}

        <div class="mb-8">
            <h2 class="text-lg font-semibold mb-4">Priority Review Queue ({transaction_count} transactions)</h2>
            <p class="text-gray-600 mb-4">Showing high-priority transactions selected by active learning, plus quality check samples from high-confidence predictions. Only transactions above 95% confidence are auto-accepted.</p>
            {transactions_html}
        </div>

        <div class="mb-8">
            <h2 class="text-lg font-semibold mb-4">Filters</h2>
            <div class="bg-gray-50 p-4 rounded space-y-4">
                <!-- Status Filter -->
                <div>
                    <label class="block text-sm font-medium mb-2">Queue:</label>
                    <div class="flex gap-4 flex-wrap">
                        <label class="flex items-center">
                            <input type="radio" name="status" value="high_priority" checked
                                   hx-get="/api/transactions/table"
                                   hx-trigger="change"
                                   hx-target="#transaction-table"
                                   hx-include="[name='confidence_lt'], [name='search'], [name='sort_by'], [name='sort_order'], [name='category_filter'], [name='start_date'], [name='end_date']"
                                   class="mr-2">
                            Priority Review
                        </label>
                        <label class="flex items-center">
                            <input type="radio" name="status" value="pending"
                                   hx-get="/api/transactions/table"
                                   hx-trigger="change"
                                   hx-target="#transaction-table"
                                   hx-include="[name='confidence_lt'], [name='search'], [name='sort_by'], [name='sort_order'], [name='category_filter'], [name='start_date'], [name='end_date']"
                                   class="mr-2">
                            All Pending
                        </label>
                        <label class="flex items-center">
                            <input type="radio" name="status" value="reviewed"
                                   hx-get="/api/transactions/table"
                                   hx-trigger="change"
                                   hx-target="#transaction-table"
                                   hx-include="[name='confidence_lt'], [name='search'], [name='sort_by'], [name='sort_order'], [name='category_filter'], [name='start_date'], [name='end_date']"
                                   class="mr-2">
                            Auto-Accepted
                        </label>
                        <label class="flex items-center">
                            <input type="radio" name="status" value="all"
                                   hx-get="/api/transactions/table"
                                   hx-trigger="change"
                                   hx-target="#transaction-table"
                                   hx-include="[name='confidence_lt'], [name='search'], [name='sort_by'], [name='sort_order'], [name='category_filter'], [name='start_date'], [name='end_date']"
                                   class="mr-2">
                            All Transactions
                        </label>
                    </div>
                </div>
                
                <!-- Search -->
                <div>
                    <label class="block text-sm font-medium mb-2">Search:</label>
                    <input type="text" name="search" placeholder="Search transactions..."
                           hx-get="/api/transactions/table"
                           hx-trigger="input changed delay:300ms"
                           hx-target="#transaction-table"
                           hx-include="[name='status']:checked, [name='confidence_lt'], [name='sort_by'], [name='sort_order'], [name='category_filter'], [name='start_date'], [name='end_date']"
                           class="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                </div>
                
                <!-- Category Filter -->
                <div>
                    <label class="block text-sm font-medium mb-2">Filter by Category:</label>
                    <select name="category_filter"
                            hx-get="/api/transactions/table"
                            hx-trigger="change"
                            hx-target="#transaction-table"
                            hx-include="[name='status']:checked, [name='confidence_lt'], [name='search'], [name='sort_by'], [name='sort_order'], [name='category_filter'], [name='start_date'], [name='end_date']"
                            class="w-full px-3 py-2 border border-gray-300 rounded-md text-sm">
                        <option value="">All Categories</option>
                        <option value="uncategorized">Uncategorized</option>
                        {_generate_category_options(categories)}
                    </select>
                </div>

                <!-- Date Range Filter -->
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                        <label class="block text-sm font-medium mb-2">Start Date:</label>
                        <input type="date" name="start_date"
                               hx-get="/api/transactions/table"
                               hx-trigger="change"
                               hx-target="#transaction-table"
                               hx-include="[name='status']:checked, [name='confidence_lt'], [name='search'], [name='sort_by'], [name='sort_order'], [name='category_filter'], [name='start_date'], [name='end_date']"
                               class="w-full px-3 py-2 border border-gray-300 rounded-md text-sm">
                    </div>
                    <div>
                        <label class="block text-sm font-medium mb-2">End Date:</label>
                        <input type="date" name="end_date"
                               hx-get="/api/transactions/table"
                               hx-trigger="change"
                               hx-target="#transaction-table"
                               hx-include="[name='status']:checked, [name='confidence_lt'], [name='search'], [name='sort_by'], [name='sort_order'], [name='category_filter'], [name='start_date'], [name='end_date']"
                               class="w-full px-3 py-2 border border-gray-300 rounded-md text-sm">
                    </div>
                </div>

                <!-- Confidence Threshold (only for pending) -->
                <div id="confidence-filter">
                    <label class="block text-sm font-medium mb-2">Confidence threshold:</label>
                    <input type="range" name="confidence_lt"
                           min="0" max="1" step="0.1" value="0.8"
                           hx-get="/api/transactions/table"
                           hx-trigger="change throttle:500ms"
                           hx-target="#transaction-table"
                           hx-include="[name='status']:checked, [name='search'], [name='sort_by'], [name='sort_order'], [name='category_filter'], [name='start_date'], [name='end_date']"
                           class="w-full">
                    <p id="threshold-display" class="text-sm text-gray-600 mt-2">
                        Show transactions with confidence below 80%
                    </p>
                </div>
                
                <!-- Sorting -->
                <div class="flex gap-4">
                    <div class="flex-1">
                        <label class="block text-sm font-medium mb-2">Sort by:</label>
                        <select name="sort_by"
                                hx-get="/api/transactions/table"
                                hx-trigger="change"
                                hx-target="#transaction-table"
                                hx-include="[name='status']:checked, [name='confidence_lt'], [name='search'], [name='sort_order'], [name='category_filter'], [name='start_date'], [name='end_date']"
                                class="w-full px-3 py-2 border border-gray-300 rounded-md text-sm">
                            <option value="date" selected>Date</option>
                            <option value="confidence_score">Confidence</option>
                            <option value="amount">Amount</option>
                            <option value="name">Description</option>
                        </select>
                    </div>
                    <div class="flex-1">
                        <label class="block text-sm font-medium mb-2">Order:</label>
                        <select name="sort_order"
                                hx-get="/api/transactions/table"
                                hx-trigger="change"
                                hx-target="#transaction-table"
                                hx-include="[name='status']:checked, [name='confidence_lt'], [name='search'], [name='sort_by'], [name='category_filter'], [name='start_date'], [name='end_date']"
                                class="w-full px-3 py-2 border border-gray-300 rounded-md text-sm">
                            <option value="desc" selected>Descending</option>
                            <option value="asc">Ascending</option>
                        </select>
                    </div>
                </div>
            </div>
        </div>
    </div>
    """

    return create_page_layout("Review & Categorize - FafyCat", content)
