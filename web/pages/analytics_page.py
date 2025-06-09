"""Analytics page for FafyCat financial analytics."""

from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from web.components.layout import create_page_layout


def render_analytics_page(request: Request, session: Session) -> HTMLResponse:
    """Render the main analytics page."""
    content = """
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-3xl font-bold mb-8">📊 Financial Analytics</h1>
        
        <!-- Budget Variance Section -->
        <div class="mb-8">
            <h2 class="text-2xl font-semibold mb-4">Budget vs Actual</h2>
            <div class="bg-white rounded-lg shadow p-6">
                <div id="budget-variance-container">
                    <div class="text-center py-8 text-gray-500">
                        Loading budget variance data...
                    </div>
                </div>
                <div class="mt-4">
                    <canvas id="budget-variance-chart" width="400" height="200"></canvas>
                </div>
            </div>
        </div>

        <!-- Monthly Overview Section -->
        <div class="mb-8">
            <h2 class="text-2xl font-semibold mb-4">Monthly Overview</h2>
            <div class="bg-white rounded-lg shadow p-6">
                <div class="mb-4">
                    <label for="year-selector" class="block text-sm font-medium text-gray-700 mb-2">
                        Select Year:
                    </label>
                    <select id="year-selector" 
                            class="border border-gray-300 rounded-md px-3 py-2"
                            onchange="updateMonthlyOverview()">
                        <option value="2024">2024</option>
                        <option value="2023">2023</option>
                    </select>
                </div>
                <div id="monthly-overview-container">
                    <div class="text-center py-8 text-gray-500">
                        Loading monthly overview...
                    </div>
                </div>
                <div class="mt-4">
                    <canvas id="monthly-overview-chart" width="400" height="200"></canvas>
                </div>
            </div>
        </div>

        <!-- Category Breakdown Section -->
        <div class="mb-8">
            <h2 class="text-2xl font-semibold mb-4">Category Analysis</h2>
            <div class="bg-white rounded-lg shadow p-6">
                <div class="mb-4 grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div>
                        <label for="start-date" class="block text-sm font-medium text-gray-700 mb-2">
                            Start Date:
                        </label>
                        <input type="date" id="start-date" name="start_date"
                               class="border border-gray-300 rounded-md px-3 py-2 w-full">
                    </div>
                    <div>
                        <label for="end-date" class="block text-sm font-medium text-gray-700 mb-2">
                            End Date:
                        </label>
                        <input type="date" id="end-date" name="end_date"
                               class="border border-gray-300 rounded-md px-3 py-2 w-full">
                    </div>
                    <div>
                        <label for="category-type" class="block text-sm font-medium text-gray-700 mb-2">
                            Category Type:
                        </label>
                        <select id="category-type" name="category_type"
                                class="border border-gray-300 rounded-md px-3 py-2 w-full">
                            <option value="">All</option>
                            <option value="spending">Spending</option>
                            <option value="income">Income</option>
                            <option value="saving">Saving</option>
                        </select>
                    </div>
                </div>
                <button type="button" 
                        class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 mb-4"
                        onclick="updateCategoryAnalysis()">
                    Update Analysis
                </button>
                <div id="category-breakdown-container">
                    <div class="text-center py-8 text-gray-500">
                        Loading category breakdown...
                    </div>
                </div>
                <div class="mt-4">
                    <canvas id="category-breakdown-chart" width="400" height="200"></canvas>
                </div>
            </div>
        </div>

        <!-- Savings Tracking Section -->
        <div class="mb-8">
            <h2 class="text-2xl font-semibold mb-4">Savings Tracking</h2>
            <div class="bg-white rounded-lg shadow p-6">
                <div id="savings-tracking-container">
                    <div class="text-center py-8 text-gray-500">
                        Loading savings data...
                    </div>
                </div>
                <div class="mt-4">
                    <canvas id="savings-tracking-chart" width="400" height="200"></canvas>
                </div>
            </div>
        </div>
    </div>

    <!-- Chart.js and Analytics JavaScript -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="/static/js/analytics.js"></script>
    
    <!-- Load initial data -->
    <script>
        // Load initial data when page loads
        document.addEventListener('DOMContentLoaded', function() {
            // Load budget variance
            fetch('/api/analytics/budget-variance')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('budget-variance-container').innerHTML = '<p>Budget variance data loaded. Check chart below.</p>';
                    updateBudgetVarianceChart(data);
                });
            
            // Load monthly overview for current year
            fetch('/api/analytics/monthly-summary')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('monthly-overview-container').innerHTML = '<p>Monthly overview data loaded. Check chart below.</p>';
                    updateMonthlyOverviewChart(data);
                });
            
            // Load category breakdown for current month
            fetch('/api/analytics/category-breakdown')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('category-breakdown-container').innerHTML = '<p>Category breakdown data loaded. Check chart below.</p>';
                    updateCategoryBreakdownChart(data);
                });
            
            // Load savings tracking
            fetch('/api/analytics/savings-tracking')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('savings-tracking-container').innerHTML = '<p>Savings tracking data loaded. Check chart below.</p>';
                    updateSavingsTrackingChart(data);
                });
        });
        
        // Function to update monthly overview when year changes
        function updateMonthlyOverview() {
            const year = document.getElementById('year-selector').value;
            fetch(`/api/analytics/monthly-summary?year=${year}`)
                .then(response => response.json())
                .then(data => {
                    document.getElementById('monthly-overview-container').innerHTML = '<p>Monthly overview updated. Check chart below.</p>';
                    updateMonthlyOverviewChart(data);
                });
        }
        
        // Function to update category analysis
        function updateCategoryAnalysis() {
            const startDate = document.getElementById('start-date').value;
            const endDate = document.getElementById('end-date').value;
            const categoryType = document.getElementById('category-type').value;
            
            let url = '/api/analytics/category-breakdown?';
            if (startDate) url += `start_date=${startDate}&`;
            if (endDate) url += `end_date=${endDate}&`;
            if (categoryType) url += `category_type=${categoryType}&`;
            
            fetch(url)
                .then(response => response.json())
                .then(data => {
                    document.getElementById('category-breakdown-container').innerHTML = '<p>Category analysis updated. Check chart below.</p>';
                    updateCategoryBreakdownChart(data);
                });
        }
    </script>
    """

    return create_page_layout("Analytics - FafyCat", content)
