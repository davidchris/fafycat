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
                
                <!-- Spending Categories Chart -->
                <div class="mt-6">
                    <h3 class="text-lg font-semibold mb-3 text-red-600">💸 Spending Categories</h3>
                    <div class="bg-gray-50 rounded-lg p-4">
                        <canvas id="spending-categories-chart" height="400"></canvas>
                    </div>
                </div>
                
                <!-- Income Categories Chart -->
                <div class="mt-6">
                    <h3 class="text-lg font-semibold mb-3 text-green-600">💰 Income Categories</h3>
                    <div class="bg-gray-50 rounded-lg p-4">
                        <canvas id="income-categories-chart" height="200"></canvas>
                    </div>
                </div>
                
                <!-- Saving Categories Chart -->
                <div class="mt-6">
                    <h3 class="text-lg font-semibold mb-3 text-blue-600">💎 Saving Categories</h3>
                    <div class="bg-gray-50 rounded-lg p-4">
                        <canvas id="saving-categories-chart" height="200"></canvas>
                    </div>
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

        <!-- Year-over-Year Comparison Section -->
        <div class="mb-8">
            <h2 class="text-2xl font-semibold mb-4">Year-over-Year Category Comparison</h2>
            <div class="bg-white rounded-lg shadow p-6">
                <div class="mb-4">
                    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                        <div>
                            <label for="yoy-category-type" class="block text-sm font-medium text-gray-700 mb-2">
                                Category Type:
                            </label>
                            <select id="yoy-category-type" name="yoy_category_type"
                                    class="border border-gray-300 rounded-md px-3 py-2 w-full">
                                <option value="">All Categories</option>
                                <option value="spending">Spending Only</option>
                                <option value="income">Income Only</option>
                                <option value="saving">Saving Only</option>
                            </select>
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">
                                Years to Compare:
                            </label>
                            <div id="yoy-years-container" class="space-y-2">
                                <!-- Years checkboxes will be populated dynamically -->
                            </div>
                        </div>
                        <div>
                            <label for="yoy-view-mode" class="block text-sm font-medium text-gray-700 mb-2">
                                View Mode:
                            </label>
                            <select id="yoy-view-mode" name="yoy_view_mode"
                                    class="border border-gray-300 rounded-md px-3 py-2 w-full">
                                <option value="total">Total Amount</option>
                                <option value="monthly_avg">Monthly Average</option>
                            </select>
                        </div>
                    </div>
                    <div class="mt-4 flex gap-2">
                        <button type="button" 
                                class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600"
                                onclick="updateYearOverYearComparison()">
                            Update Comparison
                        </button>
                        <button type="button" 
                                class="bg-gray-500 text-white px-4 py-2 rounded hover:bg-gray-600"
                                onclick="exportYearOverYearData()">
                            Export to CSV
                        </button>
                    </div>
                </div>
                <div id="yoy-comparison-container">
                    <div class="text-center py-8 text-gray-500">
                        Loading year-over-year comparison...
                    </div>
                </div>
                <div class="mt-4">
                    <canvas id="yoy-comparison-chart" width="400" height="300"></canvas>
                </div>
                <div class="mt-4">
                    <div class="mb-4">
                        <label for="cumulative-category-selector" class="block text-sm font-medium text-gray-700 mb-2">
                            Select Category for Cumulative View:
                        </label>
                        <select id="cumulative-category-selector" 
                                class="border border-gray-300 rounded-md px-3 py-2 w-full md:w-1/3"
                                onchange="updateCategoryCumulativeChart()">
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
            
            // Initialize year-over-year comparison
            initializeYearOverYearComparison();
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
        
        // Initialize year-over-year comparison
        function initializeYearOverYearComparison() {
            // Get available years and populate checkboxes
            fetch('/api/analytics/year-over-year')
                .then(response => response.json())
                .then(data => {
                    const years = data.summary.years || [];
                    const container = document.getElementById('yoy-years-container');
                    container.innerHTML = '';
                    
                    years.forEach(year => {
                        const checkbox = document.createElement('div');
                        checkbox.className = 'flex items-center';
                        checkbox.innerHTML = `
                            <input type="checkbox" id="yoy-year-${year}" value="${year}" 
                                   class="mr-2" ${years.length <= 3 ? 'checked' : ''}>
                            <label for="yoy-year-${year}" class="text-sm">${year}</label>
                        `;
                        container.appendChild(checkbox);
                    });
                    
                    // Populate category selector for cumulative chart
                    populateCategorySelector();
                    
                    // Load initial comparison if years are available
                    if (years.length > 0) {
                        updateYearOverYearComparison();
                    }
                })
                .catch(error => {
                    console.error('Error initializing year-over-year comparison:', error);
                });
        }
        
        // Populate category selector for cumulative chart
        function populateCategorySelector() {
            fetch('/api/analytics/categories')
                .then(response => response.json())
                .then(data => {
                    const categories = data.categories || [];
                    const selector = document.getElementById('cumulative-category-selector');
                    selector.innerHTML = '<option value="">Select a category...</option>';
                    
                    // Sort categories by name
                    categories.sort((a, b) => a.name.localeCompare(b.name));
                    
                    categories.forEach(category => {
                        const option = document.createElement('option');
                        option.value = category.id;
                        option.textContent = `${category.name} (${category.type})`;
                        selector.appendChild(option);
                    });
                })
                .catch(error => {
                    console.error('Error loading categories:', error);
                });
        }
        
        // Update category cumulative chart
        function updateCategoryCumulativeChart() {
            const categoryId = document.getElementById('cumulative-category-selector').value;
            if (!categoryId) {
                document.getElementById('yoy-cumulative-chart').style.display = 'none';
                return;
            }
            
            // Get selected years
            const selectedYears = [];
            document.querySelectorAll('#yoy-years-container input[type="checkbox"]:checked').forEach(checkbox => {
                selectedYears.push(checkbox.value);
            });
            
            if (selectedYears.length === 0) {
                document.getElementById('yoy-cumulative-chart').style.display = 'none';
                return;
            }
            
            // Build API URL
            let url = `/api/analytics/category-cumulative?category_id=${categoryId}`;
            if (selectedYears.length > 0) url += `&years=${selectedYears.join(',')}`;
            
            fetch(url)
                .then(response => response.json())
                .then(data => {
                    if (data.category_name) {
                        updateCategoryCumulativeChartDisplay(data);
                    }
                })
                .catch(error => {
                    console.error('Error loading cumulative data:', error);
                });
        }
        
        // Update year-over-year comparison
        function updateYearOverYearComparison() {
            const categoryType = document.getElementById('yoy-category-type').value;
            const viewMode = document.getElementById('yoy-view-mode').value;
            
            // Get selected years
            const selectedYears = [];
            document.querySelectorAll('#yoy-years-container input[type="checkbox"]:checked').forEach(checkbox => {
                selectedYears.push(checkbox.value);
            });
            
            if (selectedYears.length === 0) {
                document.getElementById('yoy-comparison-container').innerHTML = 
                    '<div class="text-center py-8 text-gray-500">Please select at least one year to compare.</div>';
                return;
            }
            
            // Build API URL
            let url = '/api/analytics/year-over-year?';
            if (categoryType) url += `category_type=${categoryType}&`;
            if (selectedYears.length > 0) url += `years=${selectedYears.join(',')}&`;
            
            fetch(url)
                .then(response => response.json())
                .then(data => {
                    updateYearOverYearDisplay(data, viewMode);
                    updateYearOverYearCharts(data, viewMode);
                })
                .catch(error => {
                    document.getElementById('yoy-comparison-container').innerHTML = 
                        '<div class="text-red-600">Error loading comparison: ' + error.message + '</div>';
                });
        }
        
        // Update year-over-year comparison display
        function updateYearOverYearDisplay(data, viewMode) {
            const container = document.getElementById('yoy-comparison-container');
            const categories = data.categories || [];
            const years = data.summary.years || [];
            
            if (categories.length === 0) {
                container.innerHTML = '<div class="text-center py-8 text-gray-500">No data available for the selected criteria.</div>';
                return;
            }
            
            let html = `
                <div class="overflow-x-auto">
                    <table class="min-w-full bg-white border border-gray-200">
                        <thead class="bg-gray-50">
                            <tr>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Category
                                </th>
            `;
            
            // Add column headers for each year
            years.forEach(year => {
                html += `
                    <th class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                        ${year} ${viewMode === 'monthly_avg' ? '(Avg/Mo)' : '(Total)'}
                    </th>
                `;
            });
            
            // Add change columns if multiple years
            if (years.length > 1) {
                html += `
                    <th class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Change
                    </th>
                    <th class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                        % Change
                    </th>
                `;
            }
            
            html += `
                            </tr>
                        </thead>
                        <tbody class="bg-white divide-y divide-gray-200">
            `;
            
            // Add rows for each category
            categories.forEach(category => {
                html += '<tr>';
                html += `<td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">${category.name}</td>`;
                
                // Add values for each year
                years.forEach(year => {
                    const yearData = category.yearly_data[year] || {};
                    const value = viewMode === 'monthly_avg' ? yearData.monthly_avg : yearData.total;
                    const formattedValue = value ? `€${Math.abs(value).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}` : '€0.00';
                    html += `<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 text-right">${formattedValue}</td>`;
                });
                
                // Add change columns if multiple years
                if (years.length > 1) {
                    const lastYear = years[years.length - 1];
                    const prevYear = years[years.length - 2];
                    const changeKey = `${prevYear}_to_${lastYear}`;
                    const change = category.changes[changeKey];
                    
                    if (change) {
                        // Use the appropriate change values based on view mode
                        const absoluteChange = viewMode === 'monthly_avg' ? change.absolute_monthly : change.absolute_total;
                        const percentageChange = viewMode === 'monthly_avg' ? change.percentage_monthly : change.percentage_total;
                        
                        const changeColor = absoluteChange > 0 ? 'text-red-600' : 'text-green-600';
                        const arrow = absoluteChange > 0 ? '↑' : '↓';
                        html += `
                            <td class="px-6 py-4 whitespace-nowrap text-sm ${changeColor} text-right">
                                ${arrow} €${Math.abs(absoluteChange).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}
                            </td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm ${changeColor} text-right">
                                ${percentageChange > 0 ? '+' : ''}${percentageChange.toFixed(1)}%
                            </td>
                        `;
                    } else {
                        html += '<td colspan="2" class="px-6 py-4 text-center text-sm text-gray-500">N/A</td>';
                    }
                }
                
                html += '</tr>';
            });
            
            html += `
                        </tbody>
                    </table>
                </div>
            `;
            
            container.innerHTML = html;
        }
        
        // Export year-over-year data to CSV
        function exportYearOverYearData() {
            const categoryType = document.getElementById('yoy-category-type').value;
            const viewMode = document.getElementById('yoy-view-mode').value;
            
            // Get selected years
            const selectedYears = [];
            document.querySelectorAll('#yoy-years-container input[type="checkbox"]:checked').forEach(checkbox => {
                selectedYears.push(checkbox.value);
            });
            
            if (selectedYears.length === 0) {
                alert('Please select at least one year to export.');
                return;
            }
            
            // Build API URL
            let url = '/api/analytics/year-over-year?';
            if (categoryType) url += `category_type=${categoryType}&`;
            if (selectedYears.length > 0) url += `years=${selectedYears.join(',')}&`;
            
            fetch(url)
                .then(response => response.json())
                .then(data => {
                    const csv = generateYearOverYearCSV(data, viewMode);
                    downloadCSV(csv, `year-over-year-comparison-${new Date().toISOString().split('T')[0]}.csv`);
                })
                .catch(error => {
                    alert('Error exporting data: ' + error.message);
                });
        }
        
        // Update category cumulative chart display
        function updateCategoryCumulativeChartDisplay(data) {
            const ctx = document.getElementById('yoy-cumulative-chart');
            if (!ctx) return;
            
            // Destroy existing chart
            if (charts.categoryCumulative) {
                charts.categoryCumulative.destroy();
            }
            
            ctx.style.display = 'block';
            
            const years = data.years || [];
            const monthlyData = data.monthly_data || {};
            const categoryName = data.category_name;
            
            // Month labels
            const monthLabels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
            
            // Create datasets for each year
            const datasets = years.map((year, index) => {
                const colors = [
                    'rgb(59, 130, 246)',   // Blue
                    'rgb(34, 197, 94)',    // Green
                    'rgb(239, 68, 68)',    // Red
                    'rgb(147, 51, 234)',   // Purple
                    'rgb(245, 158, 11)'    // Amber
                ];
                
                const yearData = monthlyData[year] || { cumulative: Array(12).fill(0) };
                
                return {
                    label: year.toString(),
                    data: yearData.cumulative.map(val => Math.abs(val)),
                    borderColor: colors[index % colors.length],
                    backgroundColor: colors[index % colors.length].replace('rgb', 'rgba').replace(')', ', 0.1)'),
                    borderWidth: 3,
                    fill: false,
                    tension: 0.1,
                    pointBackgroundColor: colors[index % colors.length],
                    pointBorderColor: 'white',
                    pointBorderWidth: 2,
                    pointRadius: 4
                };
            });
            
            charts.categoryCumulative = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: monthLabels,
                    datasets: datasets
                },
                options: {
                    responsive: true,
                    plugins: {
                        title: {
                            display: true,
                            text: `${categoryName} - Monthly Cumulative Amount`,
                            font: { size: 16 }
                        },
                        legend: {
                            display: true,
                            position: 'top'
                        },
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    const year = years[context.datasetIndex];
                                    const value = context.parsed.y;
                                    const month = context.label;
                                    
                                    return `${year} ${month}: €${value.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            title: {
                                display: true,
                                text: 'Month'
                            }
                        },
                        y: {
                            beginAtZero: true,
                            title: {
                                display: true,
                                text: 'Cumulative Amount (€)'
                            },
                            ticks: {
                                callback: function(value) {
                                    return '€' + value.toLocaleString();
                                }
                            }
                        }
                    }
                }
            });
        }
        
        // Generate CSV from year-over-year data
        function generateYearOverYearCSV(data, viewMode) {
            const categories = data.categories || [];
            const years = data.summary.years || [];
            
            let csv = 'Category,Type';
            
            // Add headers for each year
            years.forEach(year => {
                csv += `,${year} ${viewMode === 'monthly_avg' ? 'Monthly Avg' : 'Total'}`;
            });
            
            if (years.length > 1) {
                csv += ',Change,% Change';
            }
            
            csv += '\\n';
            
            // Add data rows
            categories.forEach(category => {
                csv += `"${category.name}",${category.type}`;
                
                years.forEach(year => {
                    const yearData = category.yearly_data[year] || {};
                    const value = viewMode === 'monthly_avg' ? yearData.monthly_avg : yearData.total;
                    csv += `,${value || 0}`;
                });
                
                if (years.length > 1) {
                    const lastYear = years[years.length - 1];
                    const prevYear = years[years.length - 2];
                    const changeKey = `${prevYear}_to_${lastYear}`;
                    const change = category.changes[changeKey];
                    
                    if (change) {
                        // Use the appropriate change values based on view mode
                        const absoluteChange = viewMode === 'monthly_avg' ? change.absolute_monthly : change.absolute_total;
                        const percentageChange = viewMode === 'monthly_avg' ? change.percentage_monthly : change.percentage_total;
                        csv += `,${absoluteChange},${percentageChange}`;
                    } else {
                        csv += ',,';
                    }
                }
                
                csv += '\\n';
            });
            
            return csv;
        }
        
        // Download CSV file
        function downloadCSV(csv, filename) {
            const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = filename;
            link.click();
        }
    </script>
    """

    return create_page_layout("Analytics - FafyCat", content)
