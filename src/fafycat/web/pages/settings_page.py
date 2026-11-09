"""Settings and categories page."""

import html
import json
import logging

from fastapi import Request
from sqlalchemy.orm import Session

from fafycat.api.ml_insights import get_calibration_report
from fafycat.core.database import get_categories
from fafycat.ml.human_labels import count_human_labels
from fafycat.web.components.layout import create_page_layout

logger = logging.getLogger(__name__)

INACTIVE_SHOWN = 5
"""Inactive categories listed before the "Show N more" toggle."""


def _get_ml_model_status(db: Session) -> dict:
    """Get ML model status for the settings page.

    "Model loaded and ready" is reported only after the saved model actually
    loaded; a missing, corrupt, or incompatible file says why it cannot predict.
    """
    from fafycat.api.ml import load_categorizer
    from fafycat.core.database import TransactionORM

    min_training_samples = 50
    status = {
        "model_loaded": False,
        "can_predict": False,
        "training_ready": False,
        "reviewed_transactions": 0,
        "min_training_samples": min_training_samples,
        "unpredicted_transactions": 0,
        "repredictable_transactions": 0,
        "status": "Unable to check model status",
    }
    try:
        reviewed_count = count_human_labels(db)
        status.update(
            training_ready=reviewed_count >= min_training_samples,
            reviewed_transactions=reviewed_count,
            unpredicted_transactions=db.query(TransactionORM)
            .filter(TransactionORM.predicted_category_id.is_(None))
            .count(),
            repredictable_transactions=db.query(TransactionORM)
            .filter(TransactionORM.is_reviewed.is_(False), TransactionORM.predicted_category_id.is_not(None))
            .count(),
        )
    except Exception:
        logger.exception("Could not count transactions for the model status")
        return status

    try:
        categorizer = load_categorizer(db)
    except FileNotFoundError:
        status["status"] = "No model found - ready to train" if status["training_ready"] else "Not enough training data"
    except Exception as e:
        logger.warning("Saved model failed to load: %s", e)
        status.update(status=f"Model failed to load: {e}", load_error=str(e))
    else:
        classes = getattr(categorizer, "classes_", None)
        status.update(
            model_loaded=True,
            can_predict=True,
            status="Model loaded and ready",
            classes_count=len(classes) if classes is not None else 0,
        )
    return status


def render_settings_page(request: Request, db: Session):
    """Render the settings and categories page."""

    # Get all categories (including inactive ones for management)
    all_categories = get_categories(db, active_only=False)
    active_categories = [cat for cat in all_categories if cat.is_active]
    inactive_categories = [cat for cat in all_categories if not cat.is_active]

    # Group categories by type
    category_groups = {
        "spending": [cat for cat in active_categories if cat.type == "spending"],
        "income": [cat for cat in active_categories if cat.type == "income"],
        "saving": [cat for cat in active_categories if cat.type == "saving"],
    }

    # Check if we have any categories at all
    has_categories = len(active_categories) > 0

    # Get ML model status
    ml_status = _get_ml_model_status(db)
    calibration = get_calibration_report(db)

    if not has_categories:
        # Empty state - no categories exist
        content = render_empty_categories_state(ml_status, calibration)
    else:
        # Normal state - show category management
        content = render_categories_management(category_groups, inactive_categories, ml_status, calibration)

    return create_page_layout("Settings & Categories - FafyCat", content)


def render_empty_categories_state(ml_status, calibration=None):
    """Render empty state when no categories exist."""
    return f"""
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-2xl font-bold mb-6">Settings & Categories</h1>

        {render_ml_training_section(ml_status, calibration)}

        <div class="card text-center">
            <div class="mb-6">
                <svg class="mx-auto h-24 w-24 text-tertiary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1"
                          d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
                </svg>
            </div>

            <h2 class="text-xl font-semibold mb-2">No Categories Yet</h2>
            <p class="mb-6 max-w-md mx-auto">
                To get started, you need to create categories for your transactions.
                You can either import labeled data or create categories manually.
            </p>

            <div class="space-y-3">
                <div class="alert alert-info">
                    <h3 class="mb-2">Recommended: Import Labeled Data</h3>
                    <p class="text-sm mb-3">
                        If you have transaction data with categories, import it to automatically
                        discover your categories.
                    </p>
                    <code class="badge badge-saving">
                        uv run scripts/import_labeled_data.py
                    </code>
                </div>

                <div class="text-secondary">or</div>

                <button
                    onclick="showCreateCategoryModal()"
                    class="btn btn-success"
                >
                    Create Your First Category
                </button>
            </div>
        </div>
    </div>

    <script src="/static/js/repredict.js"></script>
    <script src="/static/js/settings.js"></script>
    """


def render_categories_management(category_groups, inactive_categories, ml_status, calibration=None):
    """Render category management interface."""

    # Count categories with and without budgets
    categories_with_budgets = sum(1 for group in category_groups.values() for cat in group if cat.budget > 0)
    total_active = sum(len(group) for group in category_groups.values())

    from datetime import date

    current_year = date.today().year

    content = f"""
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-2xl font-bold mb-6">Settings & Categories</h1>

        {render_ml_training_section(ml_status, calibration)}

        <!-- Summary Stats -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
            <div class="card">
                <h3 class="text-lg font-semibold">Active Categories</h3>
                <p class="stat-value text-saving">{total_active}</p>
            </div>
            <div class="card">
                <h3 class="text-lg font-semibold">With Budgets</h3>
                <p class="stat-value text-success">{categories_with_budgets}</p>
            </div>
            <div class="card">
                <h3 class="text-lg font-semibold">Inactive</h3>
                <p class="stat-value text-secondary">{len(inactive_categories)}</p>
            </div>
        </div>

        <!-- Budget Year Selector and Management -->
        {render_yearly_budget_management(current_year)}

        <!-- Budget Variance Analytics -->
        {render_budget_variance_section()}

        <!-- Category Groups -->
        <div class="space-y-8">
    """

    # Render each category type
    type_labels = {"spending": "Spending", "income": "Income", "saving": "Saving"}
    type_border_colors = {
        "spending": "border-left: 3px solid var(--color-spending)",
        "income": "border-left: 3px solid var(--color-income)",
        "saving": "border-left: 3px solid var(--color-saving)",
    }

    for cat_type, categories in category_groups.items():
        if categories:  # Only show types that have categories
            content += f"""
            <div class="card" style="{type_border_colors[cat_type]}">
                <h2 class="text-lg font-semibold mb-4">{type_labels[cat_type]} Categories</h2>
                <div class="space-y-3">
            """

            for category in categories:
                budget_display = f"\u20ac{category.budget:.0f}/month" if category.budget > 0 else "No budget set"
                budget_style = "color: var(--color-success)" if category.budget > 0 else "color: var(--text-tertiary)"
                safe_name_js = html.escape(json.dumps(category.name))

                content += f"""
                    <div class="flex items-center justify-between p-3" style="border: 1px solid var(--border-subtle); border-radius: 4px;">
                        <div>
                            <span class="font-medium">{html.escape(category.name)}</span>
                            <span class="text-sm ml-2" style="{budget_style}">{budget_display}</span>
                        </div>
                        <div class="flex space-x-2">
                            <button
                                onclick="editBudget({category.id}, {safe_name_js}, {category.budget})"
                                class="btn-ghost text-sm"
                            >
                                Edit Budget
                            </button>
                            <button
                                onclick="editCategoryType({category.id}, {safe_name_js}, '{category.type}')"
                                class="btn-ghost text-sm"
                            >
                                Edit Type
                            </button>
                            <button
                                onclick="deactivateCategory({category.id}, {safe_name_js})"
                                class="btn-ghost text-sm"
                            >
                                Deactivate
                            </button>
                        </div>
                    </div>
                """

            content += """
                </div>
            </div>
            """

    # Inactive categories section
    if inactive_categories:
        content += f"""
        <div class="card">
            <h2 class="text-lg font-semibold mb-4">
                Inactive Categories ({len(inactive_categories)})
            </h2>
            <div class="space-y-2">
        """

        for index, category in enumerate(inactive_categories):
            safe_name_js = html.escape(json.dumps(category.name))
            # Show the first few; the rest open with the toggle below.
            overflow = " data-inactive-overflow hidden" if index >= INACTIVE_SHOWN else ""
            content += f"""
                <div class="flex items-center justify-between p-2 text-sm"{overflow}>
                    <span>{html.escape(category.name)}</span>
                    <button
                        onclick="reactivateCategory({category.id}, {safe_name_js})"
                        class="btn-ghost"
                    >
                        Reactivate
                    </button>
                </div>
            """

        if len(inactive_categories) > INACTIVE_SHOWN:
            label = f"Show {len(inactive_categories) - INACTIVE_SHOWN} more"
            content += f"""
                <button type="button" class="btn-ghost text-sm" aria-expanded="false"
                        data-collapsed-label="{label}" onclick="toggleInactiveCategories(this)">{label}</button>
            """

        content += """
            </div>
        </div>
        """

    content += """
        </div>

        <!-- Add New Category Button -->
        <div class="mt-8 text-center">
            <button
                onclick="showCreateCategoryModal()"
                class="btn btn-success"
            >
                Add New Category
            </button>
        </div>
    </div>

    <script src="/static/js/repredict.js"></script>
    <script src="/static/js/settings.js"></script>
    """

    return content


def render_budget_reminder(categories_with_budgets, total_active):
    """Render budget reminder if many categories don't have budgets."""
    categories_without_budgets = total_active - categories_with_budgets

    if categories_without_budgets > 0:
        return f"""
        <div class="alert alert-warning mb-6">
            <div class="flex items-center">
                <div class="ml-3">
                    <h3 class="text-sm font-medium">
                        {categories_without_budgets} categories don't have budgets set
                    </h3>
                    <p class="text-sm">
                        Consider setting monthly budgets to track your spending goals
                        (optional but helpful for insights).
                    </p>
                </div>
            </div>
        </div>
        """

    return ""


def render_budget_variance_section():
    """Render budget variance analytics section for settings page."""
    return """
    <div class="card mb-8">
        <div class="flex items-center justify-between mb-4">
            <h2 class="text-lg font-semibold">Budget Performance</h2>
            <a href="/analytics" class="btn-ghost text-sm">
                View Full Analytics &rarr;
            </a>
        </div>

        <div id="budget-variance-summary">
            <div class="text-center py-8">
                Loading budget analysis...
            </div>
        </div>

        <div class="mt-4">
            <canvas id="budget-variance-mini-chart" width="400" height="150"></canvas>
        </div>

        <div class="mt-4 text-xs text-secondary">
            Showing year-to-date budget vs actual spending. Set budgets above to see analysis.
        </div>
    </div>

    <script>
        // Load budget variance data on page load
        document.addEventListener('DOMContentLoaded', function() {
            // Calculate year-to-date date range
            const currentYear = new Date().getFullYear();
            const startDate = `${currentYear}-01-01`;
            const endDate = new Date().toISOString().split('T')[0];

            fetch(`/api/analytics/budget-variance?start_date=${startDate}&end_date=${endDate}`)
                .then(response => response.json())
                .then(data => {
                    updateBudgetVarianceSummary(data);
                    updateBudgetVarianceMiniChart(data);
                })
                .catch(error => {
                    document.getElementById('budget-variance-summary').innerHTML =
                        '<div class="text-sm text-error">Error loading budget data</div>';
                });
        });

        function updateBudgetVarianceSummary(data) {
            const container = document.getElementById('budget-variance-summary');
            const variances = data.variances || [];
            const summary = data.summary || {};

            if (variances.length === 0) {
                container.innerHTML = `
                    <div class="text-center py-4">
                        <p>No budget data available</p>
                        <p class="text-sm mt-2 text-secondary">Set budgets for your spending categories to see variance analysis</p>
                    </div>
                `;
                return;
            }

            // Find top 3 overspending categories
            const overspending = variances.filter(v => v.is_overspent).slice(0, 3);

            let html = `
                <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                    <div class="text-center p-3">
                        <div class="stat-value">&euro;${summary.total_budget?.toFixed(0) || 0}</div>
                        <div class="stat-label">Total Budget</div>
                    </div>
                    <div class="text-center p-3">
                        <div class="stat-value">&euro;${summary.total_actual?.toFixed(0) || 0}</div>
                        <div class="stat-label">Total Spent</div>
                    </div>
                    <div class="text-center p-3">
                        <div class="stat-value">
                            &euro;${summary.total_variance?.toFixed(0) || 0}
                        </div>
                        <div class="stat-label">Variance</div>
                    </div>
                </div>
            `;

            if (overspending.length > 0) {
                html += `
                    <div class="alert alert-error">
                        <h3 class="font-medium mb-2">Budget Alerts</h3>
                        <div class="space-y-2">
                `;

                overspending.forEach(category => {
                    const overspent = Math.abs(category.variance);
                    html += `
                        <div class="flex justify-between items-center text-sm">
                            <span>${escapeHtml(category.category_name)}</span>
                            <span class="font-medium">&euro;${overspent.toFixed(0)} over</span>
                        </div>
                    `;
                });

                html += `
                        </div>
                    </div>
                `;
            } else {
                html += `
                    <div class="alert alert-success">
                        <p class="text-sm">All categories are within budget this month!</p>
                    </div>
                `;
            }

            container.innerHTML = html;
        }

        function updateBudgetVarianceMiniChart(data) {
            const ctx = document.getElementById('budget-variance-mini-chart');
            if (!ctx || !data.variances) return;

            const variances = data.variances.slice(0, 5); // Show top 5 categories

            // Destroy existing chart if exists
            if (window.budgetVarianceMiniChart) {
                window.budgetVarianceMiniChart.destroy();
            }

            const labels = variances.map(v => v.category_name);
            const budgetData = variances.map(v => v.budget);
            const actualData = variances.map(v => v.actual);

            window.budgetVarianceMiniChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [
                        {
                            label: 'Budget',
                            data: budgetData,
                            backgroundColor: 'rgba(30, 95, 175, 0.7)',
                            borderColor: 'rgb(30, 95, 175)',
                            borderWidth: 1
                        },
                        {
                            label: 'Actual',
                            data: actualData,
                            backgroundColor: variances.map(v =>
                                v.is_overspent ? 'rgba(230, 59, 46, 0.7)' : 'rgba(46, 204, 113, 0.7)'
                            ),
                            borderColor: variances.map(v =>
                                v.is_overspent ? 'rgb(230, 59, 46)' : 'rgb(46, 204, 113)'
                            ),
                            borderWidth: 1
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: true,
                            position: 'bottom'
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                callback: function(value) {
                                    return '\u20ac' + value;
                                }
                            }
                        }
                    }
                }
            });
        }
    </script>

    <!-- Chart.js for budget variance chart -->
    <script src="/static/vendor/chart-4.4.9.umd.min.js"></script>
    """


def render_yearly_budget_management(current_year):
    """Render yearly budget management section."""
    return f"""
    <div class="card mb-8">
        <div class="flex items-center justify-between mb-6">
            <h2 class="text-lg font-semibold">Yearly Budget Management</h2>

            <!-- Year Selector -->
            <div class="flex items-center space-x-4">
                <label for="budget-year-selector" class="form-label">Budget Year:</label>
                <select id="budget-year-selector" class="form-select" onchange="loadBudgetsForYear(this.value)">
                    <option value="{current_year - 1}">{current_year - 1}</option>
                    <option value="{current_year}" selected>{current_year}</option>
                    <option value="{current_year + 1}">{current_year + 1}</option>
                </select>

                <button onclick="showCopyBudgetsModal()" class="btn btn-sm btn-primary">
                    Copy from Previous Year
                </button>
            </div>
        </div>

        <!-- Budget Status Indicator -->
        <div id="budget-year-status" class="mb-4">
            <div class="text-center py-4">
                Loading budget information...
            </div>
        </div>

        <!-- Budget List Container -->
        <div id="yearly-budget-container">
            <div class="text-center py-8">
                Select a year to view and edit budgets
            </div>
        </div>
    </div>

    <!-- Copy Budgets Modal -->
    <div id="copy-budgets-modal" class="hidden fixed inset-0 bg-opacity-50 overflow-y-auto h-full w-full z-50" style="background: rgba(0,0,0,0.6)">
        <div class="relative top-20 mx-auto p-5 border w-96 shadow-lg rounded-md card">
            <h3 class="text-lg font-bold mb-4">Copy Budgets from Previous Year</h3>

            <div class="mb-4">
                <label for="source-year" class="form-label mb-2">Copy from year:</label>
                <select id="source-year" class="form-select w-full">
                    <option value="{current_year - 2}">{current_year - 2}</option>
                    <option value="{current_year - 1}" selected>{current_year - 1}</option>
                </select>
            </div>

            <div class="mb-4">
                <label for="target-year" class="form-label mb-2">Copy to year:</label>
                <select id="target-year" class="form-select w-full">
                    <option value="{current_year}" selected>{current_year}</option>
                    <option value="{current_year + 1}">{current_year + 1}</option>
                </select>
            </div>

            <div class="flex justify-end space-x-3">
                <button onclick="hideCopyBudgetsModal()" class="btn btn-secondary">
                    Cancel
                </button>
                <button onclick="copyBudgets()" class="btn btn-primary">
                    Copy Budgets
                </button>
            </div>
        </div>
    </div>

    <script>
        let currentBudgetYear = {current_year};
        let budgetData = {{}};

        // Local fallback in case main.js hasn't defined it yet
        if (typeof escapeHtml === 'undefined') {{
            function escapeHtml(text) {{
                const map = {{ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }};
                return String(text ?? '').replace(/[&<>"']/g, ch => map[ch]);
            }}
        }}

        // Load budget data when page loads
        document.addEventListener('DOMContentLoaded', function() {{
            loadBudgetsForYear({current_year});
        }});

        async function loadBudgetsForYear(year) {{
            currentBudgetYear = year;

            try {{
                // Update status
                document.getElementById('budget-year-status').innerHTML = `
                    <div class="text-center py-2">
                        Loading budgets for ${{year}}...
                    </div>
                `;

                // Fetch budget data
                const response = await fetch(`/api/budgets/${{year}}`);
                const data = await response.json();

                budgetData = data;
                renderBudgetList(data);
                updateBudgetStatus(data);

            }} catch (error) {{
                console.error('Error loading budget data:', error);
                document.getElementById('budget-year-status').innerHTML = `
                    <div class="text-center py-2 text-error">
                        Error loading budget data: ${{error.message}}
                    </div>
                `;
            }}
        }}

        function renderBudgetList(data) {{
            const container = document.getElementById('yearly-budget-container');
            const budgets = data.budgets || [];

            if (budgets.length === 0) {{
                container.innerHTML = `
                    <div class="text-center py-8">
                        <p>No categories found</p>
                    </div>
                `;
                return;
            }}

            let html = `
                <div class="space-y-3">
                    <div class="grid grid-cols-4 gap-4 pb-2" style="border-bottom: 1px solid var(--border-subtle)">
                        <div>Category</div>
                        <div>Type</div>
                        <div>Monthly Budget</div>
                        <div>Actions</div>
                    </div>
            `;

            budgets.forEach(budget => {{
                const statusIndicator = budget.has_year_specific
                    ? `<span class="badge badge-success">${{data.year}}</span>`
                    : `<span class="badge badge-neutral">Default</span>`;

                const escapedName = escapeHtml(budget.category_name);
                html += `
                    <div class="grid grid-cols-4 gap-4 items-center py-3" style="border-bottom: 1px solid var(--border-subtle)">
                        <div class="font-medium">${{escapedName}} ${{statusIndicator}}</div>
                        <div class="text-sm capitalize">${{budget.category_type}}</div>
                        <div class="font-mono">&euro;${{budget.monthly_budget.toFixed(2)}}</div>
                        <div class="flex space-x-2">
                            <button data-action="edit-yearly-budget"
                                    data-category-id="${{budget.category_id}}"
                                    data-category-name="${{escapedName}}"
                                    data-monthly-budget="${{budget.monthly_budget}}"
                                    class="btn-ghost text-sm">
                                Edit
                            </button>
                            ${{budget.has_year_specific ? `
                                <button data-action="delete-yearly-budget"
                                        data-category-id="${{budget.category_id}}"
                                        data-category-name="${{escapedName}}"
                                        class="btn-ghost text-sm">
                                    Reset
                                </button>
                            ` : ''}}
                        </div>
                    </div>
                `;
            }});

            html += '</div>';
            container.innerHTML = html;

            // Event delegation for budget action buttons
            container.addEventListener('click', function(e) {{
                const btn = e.target.closest('[data-action]');
                if (!btn) return;
                const action = btn.dataset.action;
                const categoryId = btn.dataset.categoryId;
                const categoryName = btn.dataset.categoryName;
                if (action === 'edit-yearly-budget') {{
                    editYearlyBudget(categoryId, categoryName, parseFloat(btn.dataset.monthlyBudget));
                }} else if (action === 'delete-yearly-budget') {{
                    deleteYearlyBudget(categoryId, categoryName);
                }}
            }});
        }}

        function updateBudgetStatus(data) {{
            const container = document.getElementById('budget-year-status');
            const budgets = data.budgets || [];
            const yearSpecific = budgets.filter(b => b.has_year_specific).length;
            const totalBudgets = budgets.filter(b => b.monthly_budget > 0).length;

            container.innerHTML = `
                <div class="flex justify-center space-x-6 text-sm">
                    <div class="flex items-center">
                        <span class="inline-block w-3 h-3 rounded-full mr-2" style="background: var(--color-success)"></span>
                        <span>${{yearSpecific}} year-specific budgets</span>
                    </div>
                    <div class="flex items-center">
                        <span class="inline-block w-3 h-3 rounded-full mr-2" style="background: var(--text-tertiary)"></span>
                        <span>${{totalBudgets - yearSpecific}} using defaults</span>
                    </div>
                    <div class="flex items-center">
                        <span>Total active: ${{totalBudgets}}</span>
                    </div>
                </div>
            `;
        }}

        async function editYearlyBudget(categoryId, categoryName, currentBudget) {{
            const newBudget = prompt(`Set monthly budget for "${{categoryName}}" in ${{currentBudgetYear}}:`, currentBudget);

            if (newBudget !== null && !isNaN(newBudget) && parseFloat(newBudget) >= 0) {{
                try {{
                    const response = await fetch(`/api/budgets/${{currentBudgetYear}}/${{categoryId}}?monthly_budget=${{parseFloat(newBudget)}}`, {{
                        method: 'PUT',
                        headers: {{ 'Content-Type': 'application/json' }}
                    }});

                    if (response.ok) {{
                        // Reload budget data
                        await loadBudgetsForYear(currentBudgetYear);
                    }} else {{
                        const error = await response.json();
                        alert('Error updating budget: ' + error.detail);
                    }}
                }} catch (error) {{
                    alert('Error updating budget: ' + error.message);
                }}
            }}
        }}

        async function deleteYearlyBudget(categoryId, categoryName) {{
            if (confirm(`Reset "${{categoryName}}" budget for ${{currentBudgetYear}} to default? This will remove the year-specific budget.`)) {{
                try {{
                    const response = await fetch(`/api/budgets/${{currentBudgetYear}}/${{categoryId}}`, {{
                        method: 'DELETE'
                    }});

                    if (response.ok) {{
                        // Reload budget data
                        await loadBudgetsForYear(currentBudgetYear);
                    }} else {{
                        const error = await response.json();
                        alert('Error deleting budget: ' + error.detail);
                    }}
                }} catch (error) {{
                    alert('Error deleting budget: ' + error.message);
                }}
            }}
        }}

        function showCopyBudgetsModal() {{
            document.getElementById('copy-budgets-modal').classList.remove('hidden');
        }}

        function hideCopyBudgetsModal() {{
            document.getElementById('copy-budgets-modal').classList.add('hidden');
        }}

        async function copyBudgets() {{
            const sourceYear = document.getElementById('source-year').value;
            const targetYear = document.getElementById('target-year').value;

            try {{
                const response = await fetch(`/api/budgets/${{targetYear}}/copy-from/${{sourceYear}}`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }}
                }});

                const result = await response.json();

                if (response.ok) {{
                    alert(`Successfully copied ${{result.copied_count}} budgets from ${{sourceYear}} to ${{targetYear}}`);
                    hideCopyBudgetsModal();

                    // Reload if we're viewing the target year
                    if (currentBudgetYear == targetYear) {{
                        await loadBudgetsForYear(targetYear);
                    }}
                }} else {{
                    alert('Error copying budgets: ' + result.detail);
                }}
            }} catch (error) {{
                alert('Error copying budgets: ' + error.message);
            }}
        }}
    </script>
    """


def render_calibration_table(calibration):
    """Render the per-band agreement report that justifies the threshold.

    Args:
        calibration: A ``CalibrationReport`` from ``fafycat.api.ml_insights``.

    Returns:
        An HTML fragment: one row per confidence band, with the bands the
        current Auto-approve Threshold already auto-accepts marked.
    """
    rows = ""
    for band in calibration.bands:
        auto_accepted = band.upper > calibration.threshold
        marker = (
            ' <span class="text-xs text-secondary" title="Auto-accepted at the current threshold">auto</span>'
            if auto_accepted
            else ""
        )
        row_style = "background: var(--bg-subtle, rgba(255,255,255,0.04))" if auto_accepted else ""
        agreement = f"{band.agreement_rate:.0%}" if band.agreement_rate is not None else "&mdash;"
        rows += f"""
                <tr style="{row_style}">
                    <td class="font-mono">{band.label}{marker}</td>
                    <td>{band.reviewed}</td>
                    <td>{band.kept}</td>
                    <td>{band.overridden}</td>
                    <td>{agreement}</td>
                </tr>"""

    return f"""
    <div class="mt-4">
        <h4 class="form-label mb-2">How well calibrated is the model?</h4>
        <p class="text-xs mb-3">
            Bands where agreement is at or near 100% are safe to auto-accept, so the threshold belongs at the
            lower edge of the lowest such band. Auto-accepted transactions later corrected:
            {calibration.auto_accepted_overridden}.
        </p>
        <div class="table-container">
            <table class="w-full text-sm">
                <thead>
                    <tr>
                        <th>Confidence</th>
                        <th>Reviewed</th>
                        <th>Kept</th>
                        <th>Overridden</th>
                        <th>Agreement</th>
                    </tr>
                </thead>
                <tbody>{rows}
                </tbody>
            </table>
        </div>
        <p class="text-xs mt-2 text-secondary">
            Counted over transactions a person categorised that have a prediction; auto-accepted and
            bulk-approved ones are left out. Confidence is the latest prediction's
            score, which is not always the score shown when the transaction was reviewed.
        </p>
    </div>
    """


def render_ml_settings_subsection(calibration=None):
    """Render the auto-approve threshold control and its calibration evidence.

    Args:
        calibration: A ``CalibrationReport``, or None to omit the table.
    """
    calibration_table = render_calibration_table(calibration) if calibration is not None else ""
    return (
        """
    <div class="mt-4 pt-4 border-t" style="border-color: var(--border-subtle)">
        <h4 class="form-label mb-2">Auto-Approve Threshold</h4>
        <p class="text-xs mb-3">
            Predictions with confidence at or above this threshold are automatically accepted.
            Lower values auto-approve more transactions; higher values require more manual review.
        </p>
        <div class="flex items-center gap-4">
            <input type="range" id="thresholdSlider" min="0.50" max="0.99" step="0.01" value="0.90"
                   class="flex-1 h-2 rounded-lg appearance-none cursor-pointer"
                   oninput="document.getElementById('thresholdValue').textContent = parseFloat(this.value).toFixed(2)">
            <span id="thresholdValue" class="text-sm font-mono font-bold w-12 text-right">0.90</span>
        </div>
        <div class="flex justify-between text-xs mt-1 mb-3">
            <span>0.50 (more auto-approve)</span>
            <span>0.99 (stricter)</span>
        </div>
        <button onclick="saveThreshold()" id="saveThresholdBtn"
                class="btn btn-sm btn-primary">
            Save Threshold
        </button>
        <span id="thresholdSaveStatus" class="text-xs ml-2"></span>
"""
        + calibration_table
        + """
    </div>

    <script>
        // Load current threshold on page load
        window._autoApproveThreshold = 0.90;
        document.addEventListener('DOMContentLoaded', function() {
            fetch('/api/ml/settings')
                .then(r => r.json())
                .then(data => {
                    const val = parseFloat(data.auto_approve_threshold).toFixed(2);
                    window._autoApproveThreshold = parseFloat(val);
                    const slider = document.getElementById('thresholdSlider');
                    const display = document.getElementById('thresholdValue');
                    if (slider) slider.value = val;
                    if (display) display.textContent = val;
                })
                .catch(() => {});
        });

        function saveThreshold() {
            const value = parseFloat(document.getElementById('thresholdSlider').value);
            const btn = document.getElementById('saveThresholdBtn');
            const status = document.getElementById('thresholdSaveStatus');
            btn.disabled = true;
            status.textContent = 'Saving...';

            fetch('/api/ml/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ auto_approve_threshold: value })
            })
            .then(r => {
                if (!r.ok) return r.json().then(d => { throw new Error(d.detail || 'Save failed'); });
                return r.json();
            })
            .then(data => {
                window._autoApproveThreshold = parseFloat(data.auto_approve_threshold);
                status.textContent = 'Saved! (' + parseFloat(data.auto_approve_threshold).toFixed(2) + ')';
                btn.disabled = false;
                setTimeout(() => { status.textContent = ''; }, 3000);
            })
            .catch(err => {
                status.textContent = 'Error: ' + err.message;
                btn.disabled = false;
            });
        }
    </script>
    """
    )


def render_ml_training_section(ml_status, calibration=None):
    """Render ML model training section based on current status."""
    model_loaded = ml_status.get("model_loaded", False)
    can_predict = ml_status.get("can_predict", False)
    training_ready = ml_status.get("training_ready", False)
    reviewed_count = ml_status.get("reviewed_transactions", 0)
    min_required = ml_status.get("min_training_samples", 50)
    unpredicted_count = ml_status.get("unpredicted_transactions", 0)
    repredictable_count = ml_status.get("repredictable_transactions", 0)
    load_error = ml_status.get("load_error")
    load_error_html = (
        f'<p class="font-medium">The saved model cannot be used: {html.escape(load_error)}</p>' if load_error else ""
    )

    # Determine alert type and content based on status
    if model_loaded and can_predict:
        # Model is working - show success status
        classes_count = ml_status.get("classes_count", 0)

        # Build predict button (blue) - only shown when there are unpredicted transactions
        predict_button = ""
        if unpredicted_count > 0:
            predict_button = f"""
                        <button
                            onclick="confirmAndPredictUnpredicted({unpredicted_count}, this)"
                            class="btn btn-sm btn-primary"
                            title="Run ML predictions on transactions without predictions"
                        >
                            Predict {unpredicted_count} Transactions
                        </button>"""

        # Build re-predict button (orange) - only shown when there are unreviewed predicted transactions
        repredict_button = ""
        if repredictable_count > 0:
            repredict_button = f"""
                        <button
                            onclick="confirmAndRepredict({repredictable_count}, this)"
                            class="btn btn-sm btn-secondary"
                            title="Re-run predictions on unreviewed transactions with the current model"
                        >
                            Re-predict {repredictable_count} Transactions
                        </button>"""

        return f"""
        <div class="mb-8 alert alert-success">
            <div class="flex items-start">
                <div class="ml-3 flex-1">
                    <h3 class="text-lg font-semibold">ML Model Status</h3>
                    <div class="mt-2 text-sm">
                        <p class="font-medium">Model is loaded and working!</p>
                        <p class="mt-1">Trained on {classes_count} categories &bull; {
            unpredicted_count
        } without predictions &bull; {repredictable_count} pending review &bull; <a href="/rules">Merchant rules</a></p>
                    </div>
                    <div class="mt-4 flex gap-3">
                        <button
                            onclick="retrainModel()"
                            class="btn btn-sm btn-success"
                        >
                            Retrain Model
                        </button>{predict_button}{repredict_button}
                    </div>
                    {render_ml_settings_subsection(calibration)}
                    </div>
                </div>
            </div>
        </div>
        """

    if training_ready:
        # Ready to train - show action button
        return f"""
        <div class="mb-8 alert alert-info">
            <div class="flex items-start">
                <div class="ml-3 flex-1">
                    <h3 class="text-lg font-semibold">ML Model Training</h3>
                    <div class="mt-2 text-sm">
                        {load_error_html}
                        <p class="font-medium">{"Retrain to replace it." if load_error else "Ready to train your first ML model!"}</p>
                        <p class="mt-1">You have {reviewed_count} reviewed transactions (requires {min_required}+)</p>
                        <p class="mt-1 text-xs">Training will analyze your categorization patterns to predict future transactions.</p>
                    </div>
                    <div class="mt-4">
                        <button
                            onclick="trainModel()"
                            id="trainButton"
                            class="btn btn-primary"
                        >
                            <svg class="mr-2 h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                                <path fill-rule="evenodd" d="M11.3 1.046A1 1 0 0112 2v5h4a1 1 0 01.82 1.573l-7 10A1 1 0 018 18v-5H4a1 1 0 01-.82-1.573l7-10a1 1 0 011.12-.38z" clip-rule="evenodd" />
                            </svg>
                            Train ML Model Now
                        </button>
                    </div>
                </div>
            </div>
        </div>
        """

    # Not enough data - show requirements
    return f"""
        <div class="mb-8 alert alert-warning">
            <div class="flex items-start">
                <div class="ml-3 flex-1">
                    <h3 class="text-lg font-semibold">ML Model Training</h3>
                    <div class="mt-2 text-sm">
                        {load_error_html}
                        <p class="font-medium">Need more training data</p>
                        <p class="mt-1">You have {reviewed_count} reviewed transactions, need at least {min_required}</p>
                        <p class="mt-1 text-xs">Import and manually categorize more transactions to enable ML training.</p>
                    </div>
                    <div class="mt-4">
                        <a href="/" class="btn btn-sm btn-secondary">
                            Go to Import Page
                        </a>
                    </div>
                </div>
            </div>
        </div>
        """
