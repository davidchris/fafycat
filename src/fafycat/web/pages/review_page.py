"""Review and categorize transactions page."""

import html

from fastapi import Request
from sqlalchemy.orm import Session

from fafycat.api.dependencies import get_db_manager
from fafycat.api.ml_insights import TrainingRecency, get_training_recency
from fafycat.api.services import CategoryService, TransactionService
from fafycat.core.config import AppConfig
from fafycat.core.database import TransactionORM
from fafycat.ml.prediction_pipeline import get_auto_approve_threshold
from fafycat.web.components.layout import create_page_layout
from fafycat.web.components.transaction_table import render_table


def _get_model_status_alert():
    """Get model status and return HTML alert if model needs training."""
    try:
        # Get ML status directly without HTTP call
        from fafycat.core.database import DatabaseManager

        config = AppConfig()
        db_manager = DatabaseManager(config)

        with db_manager.get_session() as db_session:
            # Same filename rule as the ML API, which picks by config.
            model_filename = "ensemble_categorizer.pkl" if config.ml.use_ensemble else "categorizer.pkl"
            model_path = config.ml.model_dir / model_filename

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
                <div class="mb-6 alert alert-info">
                    <div class="flex items-start">
                        <div class="flex-1">
                            <h3 class="text-sm font-medium">
                                Ready to train ML model
                            </h3>
                            <div class="mt-2 text-sm">
                                <p>You have {reviewed_count} reviewed transactions ready for training.
                                {unpredicted_count} transactions are missing predictions.</p>
                            </div>
                            <div class="mt-4">
                                <a href="/settings"
                                   class="btn btn-primary btn-sm">
                                    Train Model Now
                                </a>
                            </div>
                        </div>
                        <div class="ml-auto">
                            <button type="button"
                                    data-dismiss-alert
                                    aria-label="Dismiss"
                                    class="opacity-60 hover:opacity-100">
                                &times;
                            </button>
                        </div>
                    </div>
                </div>
                """

            # Show not enough data alert
            reviewed_count = status.get("reviewed_transactions", 0)
            min_required = status.get("min_training_samples", 50)

            return f"""
                <div class="mb-6 alert alert-warning">
                    <div class="flex items-start">
                        <div class="ml-3">
                            <h3 class="text-sm font-medium">
                                More training data needed
                            </h3>
                            <div class="mt-2 text-sm">
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


def _recency_sentence(recency: TrainingRecency) -> str:
    """Phrase the training-recency counter. Mirrors ``recencyText`` in review.js."""
    count = recency.reviews_since_training
    noun = "review" if count == 1 else "reviews"
    if recency.last_trained_at is None:
        return f"{count} {noun} recorded. The model has never been trained."
    return f"{count} {noun} since the model was last trained ({recency.last_trained_at.strftime('%d %b %Y')})"


def _render_training_recency(session: Session) -> str:
    """Render the training-recency counter with the retrain-and-re-predict button.

    The button is the whole feedback loop in one click: retrain on everything
    reviewed so far, then re-score the transactions still in the queue. It is
    hidden until there is enough labelled data to train at all.

    Args:
        session: Open database session.

    Returns:
        An HTML fragment to place above the review queue.
    """
    recency = get_training_recency(session)
    min_samples = AppConfig().ml.min_training_samples
    reviewed_count = (
        session.query(TransactionORM)
        .filter(TransactionORM.is_reviewed, TransactionORM.category_id.is_not(None))
        .count()
    )

    if reviewed_count >= min_samples:
        action = """
            <button type="button" id="retrain-repredict-btn" class="btn btn-sm btn-primary">
                Retrain and re-predict the queue
            </button>"""
    else:
        action = f"""
            <span class="text-sm text-secondary">
                Need at least {min_samples} reviewed transactions to train ({reviewed_count} so far).
            </span>"""

    return f"""
    <div id="training-recency" class="card mb-6">
        <div class="flex flex-wrap items-center justify-between gap-4">
            <div>
                <p id="training-recency-text" class="text-sm font-medium">{_recency_sentence(recency)}</p>
                <p class="text-xs text-secondary mt-1">
                    Retraining folds your corrections into the model, then re-scores everything left in the queue.
                </p>
            </div>{action}
        </div>
        <div id="retrain-alert" hidden></div>
    </div>
    """


def _generate_category_options(categories):
    """Generate category options for the filter dropdown."""
    options = ""
    for cat in categories:
        escaped = html.escape(cat.name)
        options += f'<option value="{escaped}">{escaped}</option>'
    return options


def render_review_page(request: Request):
    """Render the review and categorize transactions page."""
    db_manager = get_db_manager(request)
    threshold = 0.0

    try:
        with db_manager.get_session() as session:
            # Default view: everything not yet reviewed, least confident first.
            result = TransactionService.get_transactions_with_pagination(
                session=session,
                skip=0,
                limit=50,
                is_reviewed=False,
                sort_by="confidence_score",
                sort_order="asc",
                search="",
            )
            threshold = get_auto_approve_threshold(session)

            categories = CategoryService.get_categories(session)

            transactions_html = render_table(result["transactions"], categories, result["pagination_info"])

            transaction_count = result["pagination_info"]["total_count"]
            training_recency_html = _render_training_recency(session)

    except Exception as e:
        # Fallback in case of database error
        transactions_html = f"""
        <div class="alert alert-error">
            <p>Error loading transactions: {html.escape(str(e))}</p>
        </div>
        """
        transaction_count = 0
        categories = []
        training_recency_html = ""

    # Get model status alert
    model_alert = _get_model_status_alert()

    content = f"""
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-2xl font-bold mb-6">Review & Categorize</h1>

        {model_alert}

        {training_recency_html}

        <div class="mb-8">
            <h2 class="text-lg font-semibold mb-4">Needs review ({transaction_count} transactions)</h2>
            <p class="text-secondary mb-4">Predictions at or above {threshold:.0%} confidence are auto-accepted. Everything else is listed here, least confident first, until you save a category.</p>
            {transactions_html}
        </div>

        <div class="mb-8">
            <h2 class="text-lg font-semibold mb-4">Filters</h2>
            <div class="card space-y-4">
                <!-- Status Filter -->
                <div>
                    <label class="block text-sm font-medium mb-2">Show:</label>
                    <div class="flex gap-4 flex-wrap">
                        <label class="flex items-center">
                            <input type="radio" name="status" value="pending" checked
                                   hx-get="/api/transactions/table"
                                   hx-trigger="change"
                                   hx-target="#transaction-table"
                                   hx-include="[name='search'], [name='sort_by'], [name='sort_order'], [name='category_filter'], [name='start_date'], [name='end_date']"
                                   class="mr-2">
                            Needs review
                        </label>
                        <label class="flex items-center">
                            <input type="radio" name="status" value="reviewed"
                                   hx-get="/api/transactions/table"
                                   hx-trigger="change"
                                   hx-target="#transaction-table"
                                   hx-include="[name='search'], [name='sort_by'], [name='sort_order'], [name='category_filter'], [name='start_date'], [name='end_date']"
                                   class="mr-2">
                            Reviewed
                        </label>
                        <label class="flex items-center">
                            <input type="radio" name="status" value="all"
                                   hx-get="/api/transactions/table"
                                   hx-trigger="change"
                                   hx-target="#transaction-table"
                                   hx-include="[name='search'], [name='sort_by'], [name='sort_order'], [name='category_filter'], [name='start_date'], [name='end_date']"
                                   class="mr-2">
                            All transactions
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
                           hx-include="[name='status']:checked, [name='sort_by'], [name='sort_order'], [name='category_filter'], [name='start_date'], [name='end_date']"
                           class="form-input">
                </div>
                
                <!-- Category Filter -->
                <div>
                    <label class="block text-sm font-medium mb-2">Filter by Category:</label>
                    <select name="category_filter"
                            hx-get="/api/transactions/table"
                            hx-trigger="change"
                            hx-target="#transaction-table"
                            hx-include="[name='status']:checked, [name='search'], [name='sort_by'], [name='sort_order'], [name='category_filter'], [name='start_date'], [name='end_date']"
                            class="form-select">
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
                               hx-include="[name='status']:checked, [name='search'], [name='sort_by'], [name='sort_order'], [name='category_filter'], [name='start_date'], [name='end_date']"
                               class="form-select">
                    </div>
                    <div>
                        <label class="block text-sm font-medium mb-2">End Date:</label>
                        <input type="date" name="end_date"
                               hx-get="/api/transactions/table"
                               hx-trigger="change"
                               hx-target="#transaction-table"
                               hx-include="[name='status']:checked, [name='search'], [name='sort_by'], [name='sort_order'], [name='category_filter'], [name='start_date'], [name='end_date']"
                               class="form-select">
                    </div>
                </div>

                <!-- Sorting -->
                <div class="flex gap-4">
                    <div class="flex-1">
                        <label class="block text-sm font-medium mb-2">Sort by:</label>
                        <select name="sort_by"
                                hx-get="/api/transactions/table"
                                hx-trigger="change"
                                hx-target="#transaction-table"
                                hx-include="[name='status']:checked, [name='search'], [name='sort_order'], [name='category_filter'], [name='start_date'], [name='end_date']"
                                class="form-select">
                            <option value="confidence_score" selected>Confidence</option>
                            <option value="date">Date</option>
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
                                hx-include="[name='status']:checked, [name='search'], [name='sort_by'], [name='category_filter'], [name='start_date'], [name='end_date']"
                                class="form-select">
                            <option value="asc" selected>Ascending</option>
                            <option value="desc">Descending</option>
                        </select>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script src="/static/js/review.js" defer></script>
    """

    return create_page_layout("Review & Categorize - FafyCat", content)
