"""Settings and categories page."""

from fastapi import Request
from sqlalchemy.orm import Session

from src.fafycat.core.database import get_categories
from web.components.layout import create_page_layout


def _get_ml_model_status():
    """Get ML model status for settings page."""
    try:
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

            if not model_path.exists():
                return {
                    "model_loaded": False,
                    "can_predict": False,
                    "training_ready": training_ready,
                    "reviewed_transactions": reviewed_count,
                    "min_training_samples": min_training_samples,
                    "unpredicted_transactions": unpredicted_count,
                    "status": "No model found - ready to train" if training_ready else "Not enough training data",
                }

            # If model exists, assume it's working (avoiding model loading here for speed)
            return {
                "model_loaded": True,
                "can_predict": True,
                "training_ready": training_ready,
                "reviewed_transactions": reviewed_count,
                "min_training_samples": min_training_samples,
                "unpredicted_transactions": unpredicted_count,
                "status": "Model loaded and ready",
            }

    except Exception:
        return {
            "model_loaded": False,
            "can_predict": False,
            "training_ready": False,
            "reviewed_transactions": 0,
            "min_training_samples": 50,
            "unpredicted_transactions": 0,
            "status": "Unable to check model status",
        }


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

    # Get ML model status
    ml_status = _get_ml_model_status()

    if not has_categories:
        # Empty state - no categories exist
        content = render_empty_categories_state(ml_status)
    else:
        # Normal state - show category management
        content = render_categories_management(category_groups, inactive_categories, ml_status)

    return create_page_layout("Settings & Categories - FafyCat", content)


def render_empty_categories_state(ml_status):
    """Render empty state when no categories exist."""
    return f"""
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-2xl font-bold mb-6">Settings & Categories</h1>
        
        {render_ml_training_section(ml_status)}

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
        function showCreateCategoryModal() {{
            alert('Create category functionality will be implemented here');
        }}

        function trainModel() {{
            const trainButton = document.getElementById('trainButton');
            if (trainButton) {{
                trainButton.disabled = true;
                trainButton.innerHTML = '<svg class="animate-spin mr-2 h-4 w-4" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>Training...';
            }}

            fetch('/api/ml/retrain', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }}
            }})
            .then(response => response.json())
            .then(data => {{
                if (data.status === 'success') {{
                    const accuracy = (data.accuracy * 100).toFixed(1);
                    const samples = data.training_samples;
                    
                    // Update button to show prediction phase
                    if (trainButton) {{
                        trainButton.innerHTML = '<svg class="animate-spin mr-2 h-4 w-4" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>Auto-predicting...';
                    }}
                    
                    // Automatically predict unpredicted transactions
                    return fetch('/api/ml/predict/batch-unpredicted', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }}
                    }})
                    .then(response => response.json())
                    .then(predictData => {{
                        if (predictData.status === 'success') {{
                            const predicted = predictData.predictions_made;
                            const message = predicted > 0 
                                ? `🎉 Training and prediction completed!\\n\\n📊 Model Performance:\\n• Accuracy: ${{accuracy}}%\\n• Training samples: ${{samples}}\\n\\n⚡ Auto-Prediction Results:\\n• ${{predicted}} transactions now have predictions\\n• Ready for review on the Review page!`
                                : `🎉 Model training completed!\\n\\n📊 Model Performance:\\n• Accuracy: ${{accuracy}}%\\n• Training samples: ${{samples}}\\n\\n✨ All transactions already have predictions!`;
                            alert(message);
                        }} else {{
                            // Training succeeded but prediction failed - still show success
                            alert(`🎉 Model training completed!\\n\\nAccuracy: ${{accuracy}}%\\nTraining samples: ${{samples}}\\n\\n⚠️ Auto-prediction failed, but you can predict manually from this page.`);
                        }}
                        location.reload();
                    }})
                    .catch(error => {{
                        // Training succeeded but prediction failed - still show success
                        console.error('Auto-prediction failed:', error);
                        alert(`🎉 Model training completed!\\n\\nAccuracy: ${{accuracy}}%\\nTraining samples: ${{samples}}\\n\\n⚠️ Auto-prediction failed, but you can predict manually from this page.`);
                        location.reload();
                    }});
                }} else {{
                    throw new Error(data.detail || 'Training failed');
                }}
            }})
            .catch(error => {{
                alert('Training failed: ' + error.message);
                if (trainButton) {{
                    trainButton.disabled = false;
                    trainButton.innerHTML = '<svg class="mr-2 h-4 w-4" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M11.3 1.046A1 1 0 0112 2v5h4a1 1 0 01.82 1.573l-7 10A1 1 0 018 18v-5H4a1 1 0 01-.82-1.573l7-10a1 1 0 011.12-.38z" clip-rule="evenodd" /></svg>🚀 Train ML Model Now';
                }}
            }});
        }}

        function retrainModel() {{
            if (confirm('Retrain the ML model with current data? This will replace the existing model and automatically predict unpredicted transactions.')) {{
                trainModel();
            }}
        }}

        function predictUnpredicted() {{
            const button = event.target;
            const originalText = button.innerHTML;
            button.disabled = true;
            button.innerHTML = '<svg class="animate-spin mr-2 h-4 w-4" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>Predicting...';

            fetch('/api/ml/predict/batch-unpredicted', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }}
            }})
            .then(response => response.json())
            .then(data => {{
                if (data.status === 'success') {{
                    alert(`✅ Predicted ${{data.predictions_made}} transactions!\\n\\nYou can now review the predictions on the Review page.`);
                    location.reload();
                }} else {{
                    throw new Error(data.detail || 'Prediction failed');
                }}
            }})
            .catch(error => {{
                alert('Prediction failed: ' + error.message);
                button.disabled = false;
                button.innerHTML = originalText;
            }});
        }}
    </script>
    """


def render_categories_management(category_groups, inactive_categories, ml_status):
    """Render category management interface."""

    # Count categories with and without budgets
    categories_with_budgets = sum(1 for group in category_groups.values() for cat in group if cat.budget > 0)
    total_active = sum(len(group) for group in category_groups.values())

    content = f"""
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-2xl font-bold mb-6">Settings & Categories</h1>
        
        {render_ml_training_section(ml_status)}

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
        
        <!-- Budget Variance Analytics -->
        {render_budget_variance_section()}

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
                                onclick="editCategoryType({category.id}, '{category.name}', '{category.type}')"
                                class="text-purple-600 hover:text-purple-800 text-sm"
                            >
                                Edit Type
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

        function editCategoryType(categoryId, categoryName, currentType) {
            const newType = prompt(`Change type for "${categoryName}" (spending/income/saving):`, currentType);
            if (newType && ['spending', 'income', 'saving'].includes(newType)) {
                fetch(`/api/categories/${categoryId}/type?type=${newType}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' }
                })
                .then(response => response.json())
                .then(() => location.reload())
                .catch(error => alert('Error updating category type: ' + error));
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

        function trainModel() {
            const trainButton = document.getElementById('trainButton');
            if (trainButton) {
                trainButton.disabled = true;
                trainButton.innerHTML = '<svg class="animate-spin mr-2 h-4 w-4" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>Training...';
            }

            fetch('/api/ml/retrain', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    alert(`🎉 Model training completed!\\n\\nAccuracy: ${(data.accuracy * 100).toFixed(1)}%\\nTraining samples: ${data.training_samples}\\n\\nYour model is now ready to predict transactions!`);
                    location.reload();
                } else {
                    throw new Error(data.detail || 'Training failed');
                }
            })
            .catch(error => {
                alert('Training failed: ' + error.message);
                if (trainButton) {
                    trainButton.disabled = false;
                    trainButton.innerHTML = '<svg class="mr-2 h-4 w-4" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M11.3 1.046A1 1 0 0112 2v5h4a1 1 0 01.82 1.573l-7 10A1 1 0 018 18v-5H4a1 1 0 01-.82-1.573l7-10a1 1 0 011.12-.38z" clip-rule="evenodd" /></svg>🚀 Train ML Model Now';
                }
            });
        }

        function retrainModel() {
            if (confirm('Retrain the ML model with current data? This will replace the existing model.')) {
                trainModel();
            }
        }

        function predictUnpredicted() {
            const button = event.target;
            const originalText = button.innerHTML;
            button.disabled = true;
            button.innerHTML = '<svg class="animate-spin mr-2 h-4 w-4" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>Predicting...';

            fetch('/api/ml/predict/batch-unpredicted', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    alert(`✅ Predicted ${data.predictions_made} transactions!\\n\\nYou can now review the predictions on the Review page.`);
                    location.reload();
                } else {
                    throw new Error(data.detail || 'Prediction failed');
                }
            })
            .catch(error => {
                alert('Prediction failed: ' + error.message);
                button.disabled = false;
                button.innerHTML = originalText;
            });
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


def render_budget_variance_section():
    """Render budget variance analytics section for settings page."""
    return """
    <div class="bg-white p-6 rounded-lg shadow mb-8">
        <div class="flex items-center justify-between mb-4">
            <h2 class="text-lg font-semibold">📊 Budget Performance</h2>
            <a href="/analytics" class="text-blue-600 hover:text-blue-800 text-sm">
                View Full Analytics →
            </a>
        </div>
        
        <div id="budget-variance-summary">
            <div class="text-center py-8 text-gray-500">
                Loading budget analysis...
            </div>
        </div>
        
        <div class="mt-4">
            <canvas id="budget-variance-mini-chart" width="400" height="150"></canvas>
        </div>
        
        <div class="mt-4 text-xs text-gray-500">
            Showing current month budget vs actual spending. Set budgets above to see analysis.
        </div>
    </div>
    
    <script>
        // Load budget variance data on page load
        document.addEventListener('DOMContentLoaded', function() {
            fetch('/api/analytics/budget-variance')
                .then(response => response.json())
                .then(data => {
                    updateBudgetVarianceSummary(data);
                    updateBudgetVarianceMiniChart(data);
                })
                .catch(error => {
                    document.getElementById('budget-variance-summary').innerHTML = 
                        '<div class="text-red-500 text-sm">Error loading budget data</div>';
                });
        });
        
        function updateBudgetVarianceSummary(data) {
            const container = document.getElementById('budget-variance-summary');
            const variances = data.variances || [];
            const summary = data.summary || {};
            
            if (variances.length === 0) {
                container.innerHTML = `
                    <div class="text-center py-4">
                        <p class="text-gray-600">💡 No budget data available</p>
                        <p class="text-sm text-gray-500 mt-2">Set budgets for your spending categories to see variance analysis</p>
                    </div>
                `;
                return;
            }
            
            // Find top 3 overspending categories
            const overspending = variances.filter(v => v.is_overspent).slice(0, 3);
            
            let html = `
                <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                    <div class="text-center p-3 bg-gray-50 rounded-lg">
                        <div class="text-lg font-bold text-gray-700">€${summary.total_budget?.toFixed(0) || 0}</div>
                        <div class="text-sm text-gray-500">Total Budget</div>
                    </div>
                    <div class="text-center p-3 bg-gray-50 rounded-lg">
                        <div class="text-lg font-bold text-gray-700">€${summary.total_actual?.toFixed(0) || 0}</div>
                        <div class="text-sm text-gray-500">Total Spent</div>
                    </div>
                    <div class="text-center p-3 bg-gray-50 rounded-lg">
                        <div class="text-lg font-bold ${summary.total_variance < 0 ? 'text-red-600' : 'text-green-600'}">
                            €${summary.total_variance?.toFixed(0) || 0}
                        </div>
                        <div class="text-sm text-gray-500">Variance</div>
                    </div>
                </div>
            `;
            
            if (overspending.length > 0) {
                html += `
                    <div class="bg-red-50 border border-red-200 rounded-lg p-4">
                        <h3 class="font-medium text-red-800 mb-2">🚨 Budget Alerts</h3>
                        <div class="space-y-2">
                `;
                
                overspending.forEach(category => {
                    const overspent = Math.abs(category.variance);
                    html += `
                        <div class="flex justify-between items-center text-sm">
                            <span class="text-red-700">${category.category_name}</span>
                            <span class="text-red-600 font-medium">€${overspent.toFixed(0)} over</span>
                        </div>
                    `;
                });
                
                html += `
                        </div>
                    </div>
                `;
            } else {
                html += `
                    <div class="bg-green-50 border border-green-200 rounded-lg p-4">
                        <p class="text-green-700 text-sm">✅ All categories are within budget this month!</p>
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
                            backgroundColor: 'rgba(59, 130, 246, 0.7)',
                            borderColor: 'rgb(59, 130, 246)',
                            borderWidth: 1
                        },
                        {
                            label: 'Actual',
                            data: actualData,
                            backgroundColor: variances.map(v => 
                                v.is_overspent ? 'rgba(239, 68, 68, 0.7)' : 'rgba(34, 197, 94, 0.7)'
                            ),
                            borderColor: variances.map(v => 
                                v.is_overspent ? 'rgb(239, 68, 68)' : 'rgb(34, 197, 94)'
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
                                    return '€' + value;
                                }
                            }
                        }
                    }
                }
            });
        }
    </script>
    
    <!-- Chart.js for budget variance chart -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    """


def render_ml_training_section(ml_status):
    """Render ML model training section based on current status."""
    model_loaded = ml_status.get("model_loaded", False)
    can_predict = ml_status.get("can_predict", False)
    training_ready = ml_status.get("training_ready", False)
    reviewed_count = ml_status.get("reviewed_transactions", 0)
    min_required = ml_status.get("min_training_samples", 50)
    unpredicted_count = ml_status.get("unpredicted_transactions", 0)

    # Determine alert type and content based on status
    if model_loaded and can_predict:
        # Model is working - show success status
        classes_count = ml_status.get("classes_count", 0)
        return f"""
        <div class="mb-8 bg-green-50 border border-green-200 rounded-lg p-6">
            <div class="flex items-start">
                <div class="flex-shrink-0">
                    <svg class="h-6 w-6 text-green-400" viewBox="0 0 20 20" fill="currentColor">
                        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
                    </svg>
                </div>
                <div class="ml-3 flex-1">
                    <h3 class="text-lg font-semibold text-green-800">🤖 ML Model Status</h3>
                    <div class="mt-2 text-sm text-green-700">
                        <p class="font-medium">✅ Model is loaded and working!</p>
                        <p class="mt-1">Trained on {classes_count} categories • {
            unpredicted_count
        } transactions need predictions</p>
                    </div>
                    <div class="mt-4 flex gap-3">
                        <button 
                            onclick="retrainModel()"
                            class="inline-flex items-center px-3 py-2 text-sm font-medium text-green-700 bg-green-100 rounded-md hover:bg-green-200"
                        >
                            🔄 Retrain Model
                        </button>
                        {
            f'''
                        <button 
                            onclick="predictUnpredicted()"
                            class="inline-flex items-center px-3 py-2 text-sm font-medium text-blue-700 bg-blue-100 rounded-md hover:bg-blue-200"
                        >
                            ⚡ Predict {unpredicted_count} Transactions
                        </button>
                        '''
            if unpredicted_count > 0
            else ""
        }
                    </div>
                </div>
            </div>
        </div>
        """

    if training_ready:
        # Ready to train - show action button
        return f"""
        <div class="mb-8 bg-blue-50 border border-blue-200 rounded-lg p-6">
            <div class="flex items-start">
                <div class="flex-shrink-0">
                    <svg class="h-6 w-6 text-blue-400" viewBox="0 0 20 20" fill="currentColor">
                        <path fill-rule="evenodd" d="M11.3 1.046A1 1 0 0112 2v5h4a1 1 0 01.82 1.573l-7 10A1 1 0 018 18v-5H4a1 1 0 01-.82-1.573l7-10a1 1 0 011.12-.38z" clip-rule="evenodd" />
                    </svg>
                </div>
                <div class="ml-3 flex-1">
                    <h3 class="text-lg font-semibold text-blue-800">🤖 ML Model Training</h3>
                    <div class="mt-2 text-sm text-blue-700">
                        <p class="font-medium">Ready to train your first ML model!</p>
                        <p class="mt-1">You have {reviewed_count} reviewed transactions (requires {min_required}+)</p>
                        <p class="mt-1 text-xs text-blue-600">Training will analyze your categorization patterns to predict future transactions.</p>
                    </div>
                    <div class="mt-4">
                        <button 
                            onclick="trainModel()"
                            id="trainButton"
                            class="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
                        >
                            <svg class="mr-2 h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                                <path fill-rule="evenodd" d="M11.3 1.046A1 1 0 0112 2v5h4a1 1 0 01.82 1.573l-7 10A1 1 0 018 18v-5H4a1 1 0 01-.82-1.573l7-10a1 1 0 011.12-.38z" clip-rule="evenodd" />
                            </svg>
                            🚀 Train ML Model Now
                        </button>
                    </div>
                </div>
            </div>
        </div>
        """

    # Not enough data - show requirements
    return f"""
        <div class="mb-8 bg-yellow-50 border border-yellow-200 rounded-lg p-6">
            <div class="flex items-start">
                <div class="flex-shrink-0">
                    <svg class="h-6 w-6 text-yellow-400" viewBox="0 0 20 20" fill="currentColor">
                        <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
                    </svg>
                </div>
                <div class="ml-3 flex-1">
                    <h3 class="text-lg font-semibold text-yellow-800">🤖 ML Model Training</h3>
                    <div class="mt-2 text-sm text-yellow-700">
                        <p class="font-medium">Need more training data</p>
                        <p class="mt-1">You have {reviewed_count} reviewed transactions, need at least {min_required}</p>
                        <p class="mt-1 text-xs text-yellow-600">Import and manually categorize more transactions to enable ML training.</p>
                    </div>
                    <div class="mt-4">
                        <a href="/" class="inline-flex items-center px-3 py-2 text-sm font-medium text-yellow-700 bg-yellow-100 rounded-md hover:bg-yellow-200">
                            📊 Go to Import Page
                        </a>
                    </div>
                </div>
            </div>
        </div>
        """
