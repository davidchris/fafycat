"""Settings and categories page."""

from fastapi import Request
from sqlalchemy.orm import Session

from src.fafycat.core.database import get_categories
from web.components.layout import create_page_layout


def render_settings_page(request: Request, db: Session):
    """Render the settings and categories page."""

    # Get all categories (including inactive ones for management)
    active_categories = get_categories(db, active_only=True)
    inactive_categories = get_categories(db, active_only=False)
    inactive_categories = [cat for cat in inactive_categories if not cat.is_active]

    # Group categories by type
    category_groups = {
        "spending": [cat for cat in active_categories if cat.type == "spending"],
        "income": [cat for cat in active_categories if cat.type == "income"],
        "saving": [cat for cat in active_categories if cat.type == "saving"],
    }

    # Check if we have any categories at all
    has_categories = len(active_categories) > 0

    if not has_categories:
        # Empty state - no categories exist
        content = render_empty_categories_state()
    else:
        # Normal state - show category management
        content = render_categories_management(category_groups, inactive_categories)

    return create_page_layout("Settings & Categories - FafyCat", content)


def render_empty_categories_state():
    """Render empty state when no categories exist."""
    return """
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-2xl font-bold mb-6">Settings & Categories</h1>

        <div class="bg-white p-8 rounded-lg shadow text-center">
            <div class="mb-6">
                <svg class="mx-auto h-24 w-24 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1"
                          d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
                </svg>
            </div>

            <h2 class="text-xl font-semibold text-gray-900 mb-2">No Categories Yet</h2>
            <p class="text-gray-600 mb-6 max-w-md mx-auto">
                To get started, you need to create categories for your transactions.
                You can either import labeled data or create categories manually.
            </p>

            <div class="space-y-3">
                <div class="bg-blue-50 p-4 rounded-lg">
                    <h3 class="font-medium text-blue-900 mb-2">📊 Recommended: Import Labeled Data</h3>
                    <p class="text-blue-700 text-sm mb-3">
                        If you have transaction data with categories, import it to automatically
                        discover your categories.
                    </p>
                    <code class="bg-blue-100 text-blue-800 px-2 py-1 rounded text-sm">
                        uv run scripts/import_labeled_data.py
                    </code>
                </div>

                <div class="text-gray-500">or</div>

                <button
                    onclick="showCreateCategoryModal()"
                    class="bg-green-500 text-white px-6 py-3 rounded-lg hover:bg-green-600 transition-colors"
                >
                    🏷️ Create Your First Category
                </button>
            </div>
        </div>
    </div>

    <script>
        function showCreateCategoryModal() {
            alert('Create category functionality will be implemented here');
        }
    </script>
    """


def render_categories_management(category_groups, inactive_categories):
    """Render category management interface."""

    # Count categories with and without budgets
    categories_with_budgets = sum(1 for group in category_groups.values() for cat in group if cat.budget > 0)
    total_active = sum(len(group) for group in category_groups.values())

    content = f"""
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-2xl font-bold mb-6">Settings & Categories</h1>

        <!-- Summary Stats -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
            <div class="bg-white p-6 rounded-lg shadow">
                <h3 class="text-lg font-semibold text-gray-700">Active Categories</h3>
                <p class="text-3xl font-bold text-blue-600">{total_active}</p>
            </div>
            <div class="bg-white p-6 rounded-lg shadow">
                <h3 class="text-lg font-semibold text-gray-700">With Budgets</h3>
                <p class="text-3xl font-bold text-green-600">{categories_with_budgets}</p>
            </div>
            <div class="bg-white p-6 rounded-lg shadow">
                <h3 class="text-lg font-semibold text-gray-700">Inactive</h3>
                <p class="text-3xl font-bold text-gray-500">{len(inactive_categories)}</p>
            </div>
        </div>

        <!-- Budget Reminder -->
        {render_budget_reminder(categories_with_budgets, total_active)}

        <!-- Category Groups -->
        <div class="space-y-8">
    """

    # Render each category type
    type_icons = {"spending": "💸", "income": "💰", "saving": "🏦"}
    type_labels = {"spending": "Spending", "income": "Income", "saving": "Saving"}

    for cat_type, categories in category_groups.items():
        if categories:  # Only show types that have categories
            content += f"""
            <div class="bg-white p-6 rounded-lg shadow">
                <h2 class="text-lg font-semibold mb-4">{type_icons[cat_type]} {type_labels[cat_type]} Categories</h2>
                <div class="space-y-3">
            """

            for category in categories:
                budget_display = f"€{category.budget:.0f}/month" if category.budget > 0 else "No budget set"
                budget_class = "text-green-600" if category.budget > 0 else "text-gray-400"

                content += f"""
                    <div class="flex items-center justify-between p-3 border rounded-lg hover:bg-gray-50">
                        <div>
                            <span class="font-medium">{category.name}</span>
                            <span class="text-sm {budget_class} ml-2">{budget_display}</span>
                        </div>
                        <div class="flex space-x-2">
                            <button
                                onclick="editBudget({category.id}, '{category.name}', {category.budget})"
                                class="text-blue-600 hover:text-blue-800 text-sm"
                            >
                                Edit Budget
                            </button>
                            <button
                                onclick="deactivateCategory({category.id}, '{category.name}')"
                                class="text-gray-600 hover:text-gray-800 text-sm"
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
        <div class="bg-gray-50 p-6 rounded-lg">
            <h2 class="text-lg font-semibold mb-4 text-gray-700">
                📋 Inactive Categories ({len(inactive_categories)})
            </h2>
            <div class="space-y-2">
        """

        for category in inactive_categories[:5]:  # Show max 5 inactive
            content += f"""
                <div class="flex items-center justify-between p-2 text-sm text-gray-600">
                    <span>{category.name}</span>
                    <button
                        onclick="reactivateCategory({category.id}, '{category.name}')"
                        class="text-green-600 hover:text-green-800"
                    >
                        Reactivate
                    </button>
                </div>
            """

        if len(inactive_categories) > 5:
            content += f"<p class='text-sm text-gray-500'>... and {len(inactive_categories) - 5} more</p>"

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
                class="bg-green-500 text-white px-6 py-3 rounded-lg hover:bg-green-600 transition-colors"
            >
                ➕ Add New Category
            </button>
        </div>
    </div>

    <script>
        function editBudget(categoryId, categoryName, currentBudget) {
            const newBudget = prompt(`Set monthly budget for "${categoryName}":`, currentBudget);
            if (newBudget !== null && !isNaN(newBudget)) {
                fetch(`/api/categories/${categoryId}/budget?budget=${parseFloat(newBudget)}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' }
                })
                .then(response => response.json())
                .then(() => location.reload())
                .catch(error => alert('Error updating budget: ' + error));
            }
        }

        function deactivateCategory(categoryId, categoryName) {
            if (confirm(`Deactivate category "${categoryName}"? It will be hidden but historical data preserved.`)) {
                fetch(`/api/categories/${categoryId}`, { method: 'DELETE' })
                .then(() => location.reload())
                .catch(error => alert('Error deactivating category: ' + error));
            }
        }

        function reactivateCategory(categoryId, categoryName) {
            if (confirm(`Reactivate category "${categoryName}"?`)) {
                fetch(`/api/categories/${categoryId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ is_active: true })
                })
                .then(() => location.reload())
                .catch(error => alert('Error reactivating category: ' + error));
            }
        }

        function showCreateCategoryModal() {
            const name = prompt('Category name:');
            if (name) {
                const type = prompt('Category type (spending/income/saving):', 'spending');
                if (type && ['spending', 'income', 'saving'].includes(type)) {
                    fetch('/api/categories/', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: name, type: type, budget: 0.0 })
                    })
                    .then(() => location.reload())
                    .catch(error => alert('Error creating category: ' + error));
                }
            }
        }
    </script>
    """

    return content


def render_budget_reminder(categories_with_budgets, total_active):
    """Render budget reminder if many categories don't have budgets."""
    categories_without_budgets = total_active - categories_with_budgets

    if categories_without_budgets > 0:
        return f"""
        <div class="bg-yellow-50 border border-yellow-200 p-4 rounded-lg mb-6">
            <div class="flex items-center">
                <div class="flex-shrink-0">
                    <svg class="h-5 w-5 text-yellow-400" viewBox="0 0 20 20" fill="currentColor">
                        <path fill-rule="evenodd"
                              d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"
                              clip-rule="evenodd" />
                    </svg>
                </div>
                <div class="ml-3">
                    <h3 class="text-sm font-medium text-yellow-800">
                        💡 {categories_without_budgets} categories don't have budgets set
                    </h3>
                    <p class="text-sm text-yellow-700">
                        Consider setting monthly budgets to track your spending goals
                        (optional but helpful for insights).
                    </p>
                </div>
            </div>
        </div>
        """

    return ""
