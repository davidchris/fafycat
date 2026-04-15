"""Analytics page for FafyCat financial analytics."""

from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from web.components.layout import create_page_layout


def render_analytics_page(request: Request, session: Session) -> HTMLResponse:
    """Render the main analytics page."""
    content = """
    <div class="container mx-auto px-4 py-8">
        <div class="flex justify-between items-center mb-8">
            <h1 class="text-3xl font-bold">Financial Analytics</h1>
            <div class="flex items-center space-x-4">
                <label for="global-year-selector" class="form-label">
                    Year:
                </label>
                <select id="global-year-selector"
                        class="form-select">
                </select>
            </div>
        </div>

        <!-- Budget Variance Section -->
        <div class="mb-8">
            <h2 class="text-2xl font-semibold mb-4">Budget vs Actual</h2>
            <div class="card">
                <div id="budget-variance-container">
                    <div class="text-center py-8">
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
            <div class="card">
                <div id="monthly-overview-container">
                    <div class="text-center py-8">
                        Loading monthly overview...
                    </div>
                </div>
                <div class="mt-4">
                    <canvas id="monthly-overview-chart" width="400" height="200"></canvas>
                </div>
            </div>
        </div>

        <!-- Top Transactions Section -->
        <div class="mb-8">
            <h2 class="text-2xl font-semibold mb-4">Top Spending Transactions</h2>
            <div class="card">
                <div class="mb-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                        <label for="month-selector" class="form-label mb-2">
                            Month:
                        </label>
                        <select id="month-selector"
                                class="form-select w-full">
                            <option value="1">January</option>
                            <option value="2">February</option>
                            <option value="3">March</option>
                            <option value="4">April</option>
                            <option value="5">May</option>
                            <option value="6">June</option>
                            <option value="7">July</option>
                            <option value="8">August</option>
                            <option value="9">September</option>
                            <option value="10">October</option>
                            <option value="11">November</option>
                            <option value="12">December</option>
                        </select>
                    </div>
                    <div class="flex items-end">
                        <button type="button"
                                id="top-transactions-update-btn"
                                class="btn btn-primary h-fit"
                                >
                            Update View
                        </button>
                    </div>
                </div>
                <div id="top-transactions-container">
                    <div class="text-center py-8">
                        Loading top transactions...
                    </div>
                </div>
                <div class="mt-4">
                    <canvas id="top-transactions-chart" width="400" height="200"></canvas>
                </div>
            </div>
        </div>

        <!-- Category Breakdown Section -->
        <div class="mb-8">
            <h2 class="text-2xl font-semibold mb-4">Category Analysis</h2>
            <div class="card">
                <div class="mb-4">
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                        <div>
                            <label class="form-label mb-2">
                                Quick Month Selection:
                            </label>
                            <div class="grid grid-cols-3 gap-2">
                                <button type="button" class="quick-month-btn btn btn-secondary btn-sm" data-month="1">Jan</button>
                                <button type="button" class="quick-month-btn btn btn-secondary btn-sm" data-month="2">Feb</button>
                                <button type="button" class="quick-month-btn btn btn-secondary btn-sm" data-month="3">Mar</button>
                                <button type="button" class="quick-month-btn btn btn-secondary btn-sm" data-month="4">Apr</button>
                                <button type="button" class="quick-month-btn btn btn-secondary btn-sm" data-month="5">May</button>
                                <button type="button" class="quick-month-btn btn btn-secondary btn-sm" data-month="6">Jun</button>
                                <button type="button" class="quick-month-btn btn btn-secondary btn-sm" data-month="7">Jul</button>
                                <button type="button" class="quick-month-btn btn btn-secondary btn-sm" data-month="8">Aug</button>
                                <button type="button" class="quick-month-btn btn btn-secondary btn-sm" data-month="9">Sep</button>
                                <button type="button" class="quick-month-btn btn btn-secondary btn-sm" data-month="10">Oct</button>
                                <button type="button" class="quick-month-btn btn btn-secondary btn-sm" data-month="11">Nov</button>
                                <button type="button" class="quick-month-btn btn btn-secondary btn-sm" data-month="12">Dec</button>
                            </div>
                        </div>
                        <div>
                            <label for="category-type" class="form-label mb-2">
                                Category Type:
                            </label>
                            <select id="category-type" name="category_type"
                                    class="form-select w-full">
                                <option value="">All</option>
                                <option value="spending">Spending</option>
                                <option value="income">Income</option>
                                <option value="saving">Saving</option>
                            </select>
                        </div>
                    </div>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                            <label for="start-date" class="form-label mb-2">
                                Custom Start Date:
                            </label>
                            <input type="date" id="start-date" name="start_date"
                                   class="form-input w-full">
                        </div>
                        <div>
                            <label for="end-date" class="form-label mb-2">
                                Custom End Date:
                            </label>
                            <input type="date" id="end-date" name="end_date"
                                   class="form-input w-full">
                        </div>
                    </div>
                </div>
                <button type="button"
                        id="category-analysis-update-btn"
                        class="btn btn-primary mb-4"
                        >
                    Update Analysis
                </button>
                <div id="category-breakdown-container">
                    <div class="text-center py-8">
                        Loading category breakdown...
                    </div>
                </div>

                <!-- Spending Categories Chart -->
                <div class="mt-6">
                    <h3 class="text-lg font-semibold mb-3 text-spending">Spending Categories</h3>
                    <div class="p-4 rounded" style="position: relative; height: 400px;">
                        <canvas id="spending-categories-chart"></canvas>
                    </div>
                </div>

                <!-- Income Categories Chart -->
                <div class="mt-6">
                    <h3 class="text-lg font-semibold mb-3 text-income">Income Categories</h3>
                    <div class="p-4 rounded" style="position: relative; height: 300px;">
                        <canvas id="income-categories-chart"></canvas>
                    </div>
                </div>

                <!-- Saving Categories Chart -->
                <div class="mt-6">
                    <h3 class="text-lg font-semibold mb-3 text-saving">Saving Categories</h3>
                    <div class="p-4 rounded" style="position: relative; height: 300px;">
                        <canvas id="saving-categories-chart"></canvas>
                    </div>
                </div>
            </div>
        </div>

        <!-- Savings Tracking Section -->
        <div class="mb-8">
            <h2 class="text-2xl font-semibold mb-4">Savings Tracking</h2>
            <div class="card">
                <div id="savings-tracking-container">
                    <div class="text-center py-8">
                        Loading savings data...
                    </div>
                </div>
                <div class="mt-4">
                    <canvas id="savings-tracking-chart" width="400" height="200"></canvas>
                </div>
            </div>
        </div>

        <!-- Year-over-Year Comparison Section -->
        <div class="mb-8">
            <h2 class="text-2xl font-semibold mb-4">Year-over-Year Category Comparison</h2>
            <div class="card">
                <div class="mb-4">
                    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                        <div>
                            <label for="yoy-category-type" class="form-label mb-2">
                                Category Type:
                            </label>
                            <select id="yoy-category-type" name="yoy_category_type"
                                    class="form-select w-full">
                                <option value="">All Categories</option>
                                <option value="spending">Spending Only</option>
                                <option value="income">Income Only</option>
                                <option value="saving">Saving Only</option>
                            </select>
                        </div>
                        <div>
                            <label class="form-label mb-2">
                                Years to Compare:
                            </label>
                            <div id="yoy-years-container" class="space-y-2">
                                <!-- Years checkboxes will be populated dynamically -->
                            </div>
                        </div>
                        <div>
                            <label for="yoy-view-mode" class="form-label mb-2">
                                View Mode:
                            </label>
                            <select id="yoy-view-mode" name="yoy_view_mode"
                                    class="form-select w-full">
                                <option value="total">Total Amount</option>
                                <option value="monthly_avg">Monthly Average</option>
                            </select>
                        </div>
                    </div>
                    <div class="mt-4 flex gap-2">
                        <button type="button"
                                id="yoy-update-btn"
                                class="btn btn-primary"
                                >
                            Update Comparison
                        </button>
                        <button type="button"
                                id="yoy-export-btn"
                                class="btn btn-secondary"
                                >
                            Export to CSV
                        </button>
                    </div>
                </div>
                <div id="yoy-comparison-container">
                    <div class="text-center py-8">
                        Loading year-over-year comparison...
                    </div>
                </div>
                <div class="mt-4">
                    <canvas id="yoy-comparison-chart" width="400" height="300"></canvas>
                </div>
                <div class="mt-4">
                    <div class="mb-4">
                        <label for="cumulative-category-selector" class="form-label mb-2">
                            Select Category for Cumulative View:
                        </label>
                        <select id="cumulative-category-selector"
                                class="form-select w-full md:w-1/3">
                            <option value="">Select a category...</option>
                        </select>
                    </div>
                    <canvas id="yoy-cumulative-chart" width="400" height="200"></canvas>
                </div>
            </div>
        </div>
    </div>

    <!-- Chart.js and Analytics JavaScript -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="/static/js/analytics.js"></script>
    <script src="/static/js/analytics_yoy.js"></script>
    <script src="/static/js/analytics_page.js"></script>
    """

    return HTMLResponse(create_page_layout("Analytics - FafyCat", content))
