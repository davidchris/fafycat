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
            <h1 class="text-3xl font-bold">📊 Financial Analytics</h1>
            <div class="flex items-center space-x-4">
                <label for="global-year-selector" class="text-sm font-medium text-gray-700">
                    Year:
                </label>
                <select id="global-year-selector" 
                        class="border border-gray-300 rounded-md px-3 py-2 bg-white"
                        onchange="updateDashboardYear()">
                </select>
            </div>
        </div>
        
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

        <!-- Top Transactions Section -->
        <div class="mb-8">
            <h2 class="text-2xl font-semibold mb-4">Top Spending Transactions</h2>
            <div class="bg-white rounded-lg shadow p-6">
                <div class="mb-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                        <label for="month-selector" class="block text-sm font-medium text-gray-700 mb-2">
                            Month:
                        </label>
                        <select id="month-selector" 
                                class="border border-gray-300 rounded-md px-3 py-2 w-full"
                                onchange="updateTopTransactions()">
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
                                class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 h-fit"
                                onclick="updateTopTransactions()">
                            Update View
                        </button>
                    </div>
                </div>
                <div id="top-transactions-container">
                    <div class="text-center py-8 text-gray-500">
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
            <div class="bg-white rounded-lg shadow p-6">
                <div class="mb-4">
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">
                                Quick Month Selection:
                            </label>
                            <div class="grid grid-cols-3 gap-2">
                                <button type="button" class="quick-month-btn bg-gray-200 hover:bg-blue-500 hover:text-white px-3 py-2 rounded text-sm" data-month="1">Jan</button>
                                <button type="button" class="quick-month-btn bg-gray-200 hover:bg-blue-500 hover:text-white px-3 py-2 rounded text-sm" data-month="2">Feb</button>
                                <button type="button" class="quick-month-btn bg-gray-200 hover:bg-blue-500 hover:text-white px-3 py-2 rounded text-sm" data-month="3">Mar</button>
                                <button type="button" class="quick-month-btn bg-gray-200 hover:bg-blue-500 hover:text-white px-3 py-2 rounded text-sm" data-month="4">Apr</button>
                                <button type="button" class="quick-month-btn bg-gray-200 hover:bg-blue-500 hover:text-white px-3 py-2 rounded text-sm" data-month="5">May</button>
                                <button type="button" class="quick-month-btn bg-gray-200 hover:bg-blue-500 hover:text-white px-3 py-2 rounded text-sm" data-month="6">Jun</button>
                                <button type="button" class="quick-month-btn bg-gray-200 hover:bg-blue-500 hover:text-white px-3 py-2 rounded text-sm" data-month="7">Jul</button>
                                <button type="button" class="quick-month-btn bg-gray-200 hover:bg-blue-500 hover:text-white px-3 py-2 rounded text-sm" data-month="8">Aug</button>
                                <button type="button" class="quick-month-btn bg-gray-200 hover:bg-blue-500 hover:text-white px-3 py-2 rounded text-sm" data-month="9">Sep</button>
                                <button type="button" class="quick-month-btn bg-gray-200 hover:bg-blue-500 hover:text-white px-3 py-2 rounded text-sm" data-month="10">Oct</button>
                                <button type="button" class="quick-month-btn bg-gray-200 hover:bg-blue-500 hover:text-white px-3 py-2 rounded text-sm" data-month="11">Nov</button>
                                <button type="button" class="quick-month-btn bg-gray-200 hover:bg-blue-500 hover:text-white px-3 py-2 rounded text-sm" data-month="12">Dec</button>
                            </div>
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
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                            <label for="start-date" class="block text-sm font-medium text-gray-700 mb-2">
                                Custom Start Date:
                            </label>
                            <input type="date" id="start-date" name="start_date"
                                   class="border border-gray-300 rounded-md px-3 py-2 w-full">
                        </div>
                        <div>
                            <label for="end-date" class="block text-sm font-medium text-gray-700 mb-2">
                                Custom End Date:
                            </label>
                            <input type="date" id="end-date" name="end_date"
                                   class="border border-gray-300 rounded-md px-3 py-2 w-full">
                        </div>
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
            // Populate year selector with current year as default
            populateYearSelector();
            
            // Set current month as default for top transactions
            const currentMonth = new Date().getMonth() + 1;
            document.getElementById('month-selector').value = currentMonth;
            
            // Load all dashboard data for current year
            loadDashboardData();
        });
        
        // Populate year selector with available years
        function populateYearSelector() {
            const currentYear = new Date().getFullYear();
            const yearSelector = document.getElementById('global-year-selector');
            
            // Add YTD option first
            const ytdOption = document.createElement('option');
            ytdOption.value = 'ytd';
            ytdOption.textContent = 'YTD (Year-to-Date)';
            ytdOption.selected = true; // Default to YTD
            yearSelector.appendChild(ytdOption);
            
            // Add years from current year + 1 to 2020
            for (let year = currentYear + 1; year >= 2020; year--) {
                const option = document.createElement('option');
                option.value = year;
                option.textContent = year;
                yearSelector.appendChild(option);
            }
        }
        
        // Load all dashboard data for selected year
        function loadDashboardData() {
            const selectedYear = document.getElementById('global-year-selector').value;
            const currentYear = new Date().getFullYear();
            
            // Determine actual year and date range
            let actualYear, startDate, endDate;
            if (selectedYear === 'ytd') {
                actualYear = currentYear;
                startDate = `${currentYear}-01-01`;
                endDate = new Date().toISOString().split('T')[0]; // Today's date
            } else {
                actualYear = selectedYear;
                startDate = `${selectedYear}-01-01`;
                endDate = `${selectedYear}-12-31`;
            }
            
            // Load budget variance - use date range for YTD, year for full year
            let budgetUrl;
            if (selectedYear === 'ytd') {
                budgetUrl = `/api/analytics/budget-variance?start_date=${startDate}&end_date=${endDate}`;
            } else {
                budgetUrl = `/api/analytics/budget-variance?year=${actualYear}`;
            }
            
            fetch(budgetUrl)
                .then(response => response.json())
                .then(data => {
                    document.getElementById('budget-variance-container').innerHTML = '<p>Budget variance data loaded. Check chart below.</p>';
                    updateBudgetVarianceChart(data);
                });
            
            // Load monthly overview - use date range for YTD, year for full year  
            let monthlyUrl;
            if (selectedYear === 'ytd') {
                monthlyUrl = `/api/analytics/monthly-summary?start_date=${startDate}&end_date=${endDate}`;
            } else {
                monthlyUrl = `/api/analytics/monthly-summary?year=${actualYear}`;
            }
            
            fetch(monthlyUrl)
                .then(response => response.json())
                .then(data => {
                    document.getElementById('monthly-overview-container').innerHTML = '<p>Monthly overview data loaded. Check chart below.</p>';
                    updateMonthlyOverviewChart(data);
                });
            
            // Load category breakdown for selected year/YTD
            fetch(`/api/analytics/category-breakdown?start_date=${startDate}&end_date=${endDate}`)
                .then(response => response.json())
                .then(data => {
                    document.getElementById('category-breakdown-container').innerHTML = '<p>Category breakdown data loaded. Check chart below.</p>';
                    updateCategoryBreakdownChart(data);
                });
            
            // Load savings tracking - use date range for YTD, year for full year
            let savingsUrl;
            if (selectedYear === 'ytd') {
                savingsUrl = `/api/analytics/savings-tracking?start_date=${startDate}&end_date=${endDate}`;
            } else {
                savingsUrl = `/api/analytics/savings-tracking?year=${actualYear}`;
            }
            
            fetch(savingsUrl)
                .then(response => response.json())
                .then(data => {
                    document.getElementById('savings-tracking-container').innerHTML = '<p>Savings tracking data loaded. Check chart below.</p>';
                    updateSavingsTrackingChart(data);
                });
            
            // Load top transactions for current month
            const currentMonth = document.getElementById('month-selector').value;
            updateTopTransactions();
        }
        
        // Function to update entire dashboard when year changes
        function updateDashboardYear() {
            loadDashboardData();
            
            // Also update the category analysis date inputs to match selected year
            const selectedYear = document.getElementById('global-year-selector').value;
            const currentYear = new Date().getFullYear();
            
            if (selectedYear === 'ytd') {
                document.getElementById('start-date').value = `${currentYear}-01-01`;
                document.getElementById('end-date').value = new Date().toISOString().split('T')[0];
            } else {
                document.getElementById('start-date').value = `${selectedYear}-01-01`;
                document.getElementById('end-date').value = `${selectedYear}-12-31`;
            }
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
        
        // Function to update top transactions
        function updateTopTransactions() {
            const selectedYear = document.getElementById('global-year-selector').value;
            const selectedMonth = document.getElementById('month-selector').value;
            const currentYear = new Date().getFullYear();
            
            // Determine actual year for API call
            const actualYear = selectedYear === 'ytd' ? currentYear : selectedYear;
            
            const url = `/api/analytics/top-transactions?year=${actualYear}&month=${selectedMonth}`;
            
            fetch(url)
                .then(response => response.json())
                .then(data => {
                    updateTopTransactionsDisplay(data);
                    updateTopTransactionsChart(data);
                })
                .catch(error => {
                    document.getElementById('top-transactions-container').innerHTML = '<div class="text-red-600">Error loading top transactions: ' + error.message + '</div>';
                });
        }
        
        // Function to update top transactions display
        function updateTopTransactionsDisplay(data) {
            const container = document.getElementById('top-transactions-container');
            
            if (!data.top_transactions || data.top_transactions.length === 0) {
                container.innerHTML = '<div class="text-center py-8 text-gray-500">No transactions found for ' + data.month_name + ' ' + data.year + '</div>';
                return;
            }
            
            let html = `
                <div class="mb-4">
                    <h3 class="text-lg font-semibold text-gray-800">Top ${data.top_transactions.length} Spending Transactions - ${data.month_name} ${data.year}</h3>
                    <p class="text-sm text-gray-600">Total spending: €${data.total_spending.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</p>
                </div>
                <div class="overflow-x-auto">
                    <table class="min-w-full bg-white border border-gray-200">
                        <thead class="bg-gray-50">
                            <tr>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Date</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Description</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Category</th>
                                <th class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Amount</th>
                                <th class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">% of Total</th>
                            </tr>
                        </thead>
                        <tbody class="bg-white divide-y divide-gray-200">
            `;
            
            data.top_transactions.forEach(transaction => {
                const date = new Date(transaction.date).toLocaleDateString();
                html += `
                    <tr>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${date}</td>
                        <td class="px-6 py-4 text-sm text-gray-900">${transaction.description}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${transaction.category}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 text-right">€${transaction.amount.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 text-right">${transaction.percentage_of_total.toFixed(1)}%</td>
                    </tr>
                `;
            });
            
            html += `
                        </tbody>
                    </table>
                </div>
            `;
            
            container.innerHTML = html;
        }
        
        // Add event listeners for quick month selection
        document.addEventListener('DOMContentLoaded', function() {
            const quickMonthBtns = document.querySelectorAll('.quick-month-btn');
            quickMonthBtns.forEach(btn => {
                btn.addEventListener('click', function() {
                    const month = parseInt(this.dataset.month);
                    const selectedYear = document.getElementById('global-year-selector').value;
                    const currentYear = new Date().getFullYear();
                    const actualYear = selectedYear === 'ytd' ? currentYear : selectedYear;
                    
                    // Calculate start and end dates for the selected month
                    const startDate = `${actualYear}-${month.toString().padStart(2, '0')}-01`;
                    const endDate = new Date(actualYear, month, 0).toISOString().split('T')[0]; // Last day of month
                    
                    // Update date inputs
                    document.getElementById('start-date').value = startDate;
                    document.getElementById('end-date').value = endDate;
                    
                    // Highlight selected button
                    quickMonthBtns.forEach(b => b.classList.remove('bg-blue-500', 'text-white'));
                    quickMonthBtns.forEach(b => b.classList.add('bg-gray-200'));
                    this.classList.remove('bg-gray-200');
                    this.classList.add('bg-blue-500', 'text-white');
                    
                    // Update analysis
                    updateCategoryAnalysis();
                });
            });
            
            // Highlight current month by default
            const currentMonth = new Date().getMonth() + 1;
            const currentMonthBtn = document.querySelector(`[data-month="${currentMonth}"]`);
            if (currentMonthBtn) {
                currentMonthBtn.classList.remove('bg-gray-200');
                currentMonthBtn.classList.add('bg-blue-500', 'text-white');
            }
        });
    </script>
    """

    return create_page_layout("Analytics - FafyCat", content)
