/**
 * Analytics JavaScript for FafyCat financial analytics
 * Handles Chart.js initialization and HTMX integration
 */

// Chart instances storage
let charts = {
    budgetVariance: null,
    monthlyOverview: null,
    spendingCategories: null,
    incomeCategories: null,
    savingCategories: null,
    savingsTracking: null,
    topTransactions: null,
    yearOverYear: null,
    categoryCumulative: null
};

/**
 * Helper function to format date range for chart titles
 */
function formatDateRange(startDate, endDate, year) {
    if (year && !startDate && !endDate) {
        return year.toString();
    }
    
    if (startDate && endDate) {
        const start = new Date(startDate).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        const end = new Date(endDate).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
        return `${start} - ${end}`;
    }
    
    if (year) {
        return year.toString();
    }
    
    return new Date().getFullYear().toString();
}

/**
 * Initialize or update budget variance chart
 */
function updateBudgetVarianceChart(data) {
    const ctx = document.getElementById('budget-variance-chart');
    if (!ctx) return;

    // Destroy existing chart
    if (charts.budgetVariance) {
        charts.budgetVariance.destroy();
    }

    const variances = data.variances || [];
    const dateRange = formatDateRange(data.start_date, data.end_date, data.year);
    
    // Prepare chart data
    const labels = variances.map(v => v.category_name);
    const budgetData = variances.map(v => v.budget);
    const actualData = variances.map(v => v.actual);
    
    charts.budgetVariance = new Chart(ctx, {
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
            plugins: {
                title: {
                    display: true,
                    text: `Budget vs Actual Spending by Category (${dateRange})`
                },
                legend: {
                    display: true
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const category = variances[context.dataIndex];
                            const value = context.parsed.y;
                            const datasetLabel = context.dataset.label;
                            
                            if (datasetLabel === 'Budget') {
                                return `${datasetLabel}: €${value.toLocaleString()}`;
                            } else {
                                // For Actual spending, show additional info
                                const variance = category.variance;
                                const varianceText = variance < 0 ? 
                                    `€${Math.abs(variance).toFixed(0)} over budget` : 
                                    `€${variance.toFixed(0)} under budget`;
                                
                                return [
                                    `${datasetLabel}: €${value.toLocaleString()}`,
                                    `Variance: ${varianceText}`
                                ];
                            }
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
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

/**
 * Initialize or update monthly overview chart with stacked bars and profit/loss
 */
function updateMonthlyOverviewChart(data) {
    const ctx = document.getElementById('monthly-overview-chart');
    if (!ctx) return;

    // Destroy existing chart
    if (charts.monthlyOverview) {
        charts.monthlyOverview.destroy();
    }

    const monthlyData = data.monthly_data || [];
    const dateRange = formatDateRange(data.start_date, data.end_date, data.year);
    
    // Prepare chart data
    const labels = monthlyData.map(m => {
        const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                           'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        return monthNames[parseInt(m.month) - 1];
    });
    
    charts.monthlyOverview = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Income',
                    data: monthlyData.map(m => Math.abs(m.income)),
                    backgroundColor: 'rgba(34, 197, 94, 0.8)',
                    borderColor: 'rgb(34, 197, 94)',
                    borderWidth: 1,
                    stack: 'flow'
                },
                {
                    label: 'Spending',
                    data: monthlyData.map(m => -Math.abs(m.spending)),
                    backgroundColor: 'rgba(239, 68, 68, 0.8)',
                    borderColor: 'rgb(239, 68, 68)',
                    borderWidth: 1,
                    stack: 'flow'
                },
                {
                    label: 'Saving',
                    data: monthlyData.map(m => -Math.abs(m.saving)),
                    backgroundColor: 'rgba(59, 130, 246, 0.8)',
                    borderColor: 'rgb(59, 130, 246)',
                    borderWidth: 1,
                    stack: 'flow'
                },
                {
                    label: 'Profit/Loss',
                    data: monthlyData.map(m => m.profit_loss),
                    type: 'line',
                    backgroundColor: 'rgba(168, 85, 247, 0.1)',
                    borderColor: 'rgb(168, 85, 247)',
                    borderWidth: 3,
                    fill: false,
                    yAxisID: 'y1',
                    pointBackgroundColor: monthlyData.map(m => 
                        m.profit_loss >= 0 ? 'rgb(34, 197, 94)' : 'rgb(239, 68, 68)'
                    ),
                    pointBorderColor: 'rgb(168, 85, 247)',
                    pointRadius: 5
                },
                {
                    label: 'Cumulative Profit/Loss',
                    data: monthlyData.map(m => m.cumulative_profit_loss),
                    type: 'line',
                    backgroundColor: 'rgba(245, 158, 11, 0.1)',
                    borderColor: 'rgb(245, 158, 11)',
                    borderWidth: 2,
                    borderDash: [5, 5],
                    fill: false,
                    yAxisID: 'y1',
                    pointBackgroundColor: 'rgb(245, 158, 11)',
                    pointRadius: 3
                }
            ]
        },
        options: {
            responsive: true,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                title: {
                    display: true,
                    text: `Monthly Financial Overview (${dateRange})`,
                    font: {
                        size: 16
                    }
                },
                legend: {
                    display: true,
                    position: 'bottom'
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const label = context.dataset.label || '';
                            const value = context.parsed.y;
                            return label + ': €' + Math.abs(value).toLocaleString();
                        }
                    }
                }
            },
            scales: {
                x: {
                    stacked: true
                },
                y: {
                    stacked: true,
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Monthly Flow (€)'
                    },
                    ticks: {
                        callback: function(value) {
                            return '€' + value.toLocaleString();
                        }
                    }
                },
                y1: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    title: {
                        display: true,
                        text: 'Profit/Loss (€)'
                    },
                    grid: {
                        drawOnChartArea: false,
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
    
    // Update summary statistics
    updateMonthlySummaryStats(data);
}

/**
 * Update monthly summary statistics display
 */
function updateMonthlySummaryStats(data) {
    const yearlyTotals = data.yearly_totals || {};
    const monthlyData = data.monthly_data || [];
    
    // Calculate additional metrics with proper division by zero protection
    const monthsWithIncome = monthlyData.filter(m => m.income > 0).length;
    const monthsWithSpending = monthlyData.filter(m => m.spending < 0).length; // spending is negative
    
    const avgMonthlyIncome = (monthlyData.length > 0 && monthsWithIncome > 0) ? 
        yearlyTotals.income / monthsWithIncome : 0;
    const avgMonthlySpending = (monthlyData.length > 0 && monthsWithSpending > 0) ? 
        yearlyTotals.spending / monthsWithSpending : 0;
    const savingsRate = yearlyTotals.income > 0 ? 
        (yearlyTotals.saving / yearlyTotals.income * 100) : 0;
    
    const statsHtml = `
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6 p-4 bg-gray-50 rounded-lg">
            <div class="text-center">
                <div class="text-lg font-bold text-green-600">€${avgMonthlyIncome.toLocaleString()}</div>
                <div class="text-sm text-gray-600" title="Average monthly income across months with income transactions">Avg Monthly Income</div>
            </div>
            <div class="text-center">
                <div class="text-lg font-bold text-red-600">€${avgMonthlySpending.toLocaleString()}</div>
                <div class="text-sm text-gray-600" title="Average monthly spending across months with spending transactions">Avg Monthly Spending</div>
            </div>
            <div class="text-center">
                <div class="text-lg font-bold text-blue-600">${savingsRate.toFixed(1)}%</div>
                <div class="text-sm text-gray-600" title="Percentage of income that was saved (savings / income × 100)">Savings Rate</div>
            </div>
            <div class="text-center">
                <div class="text-lg font-bold ${yearlyTotals.profit_loss >= 0 ? 'text-green-600' : 'text-red-600'}">
                    €${yearlyTotals.profit_loss?.toLocaleString() || 0}
                </div>
                <div class="text-sm text-gray-600" title="Total income minus total spending (income - spending)">Net Profit/Loss</div>
            </div>
        </div>
    `;
    
    // Find or create stats container
    let statsContainer = document.getElementById('monthly-stats-container');
    if (!statsContainer) {
        statsContainer = document.createElement('div');
        statsContainer.id = 'monthly-stats-container';
        const chartContainer = document.getElementById('monthly-overview-chart').parentNode;
        chartContainer.appendChild(statsContainer);
    }
    statsContainer.innerHTML = statsHtml;
}

/**
 * Create horizontal bar chart for spending categories
 */
function updateSpendingCategoriesChart(data) {
    const ctx = document.getElementById('spending-categories-chart');
    if (!ctx) return;

    // Destroy existing chart
    if (charts.spendingCategories) {
        charts.spendingCategories.destroy();
    }

    const categories = data.categories || [];
    const dateRange = formatDateRange(data.start_date, data.end_date, data.year);
    
    // Get all spending categories, sorted by amount (descending)
    const spendingCategories = categories
        .filter(c => c.category_type === 'spending')
        .sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount));
    
    if (spendingCategories.length === 0) {
        ctx.style.display = 'none';
        return;
    }
    
    ctx.style.display = 'block';
    
    const labels = spendingCategories.map(c => c.category_name);
    const amounts = spendingCategories.map(c => Math.abs(c.amount));
    
    charts.spendingCategories = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Amount (€)',
                data: amounts,
                backgroundColor: 'rgba(239, 68, 68, 0.8)', // Red for spending
                borderColor: 'rgb(239, 68, 68)',
                borderWidth: 1
            }]
        },
        options: {
            indexAxis: 'y', // Horizontal bars
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                title: {
                    display: true,
                    text: `Spending Categories (${dateRange})`
                },
                legend: {
                    display: false
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const category = spendingCategories[context.dataIndex];
                            return [
                                `€${context.parsed.x.toLocaleString()}`,
                                `${category.transaction_count} transactions`,
                                `Budget: €${category.budget || 'N/A'}`
                            ];
                        }
                    }
                }
            },
            scales: {
                x: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Amount (€)'
                    },
                    ticks: {
                        callback: function(value) {
                            return '€' + value.toLocaleString();
                        }
                    }
                },
                y: {
                    title: {
                        display: true,
                        text: 'Categories'
                    }
                }
            }
        }
    });
}

/**
 * Create horizontal bar chart for income categories
 */
function updateIncomeCategoriesChart(data) {
    const ctx = document.getElementById('income-categories-chart');
    if (!ctx) return;

    // Destroy existing chart
    if (charts.incomeCategories) {
        charts.incomeCategories.destroy();
    }

    const categories = data.categories || [];
    const dateRange = formatDateRange(data.start_date, data.end_date, data.year);
    
    // Get all income categories, sorted by amount (descending)
    const incomeCategories = categories
        .filter(c => c.category_type === 'income')
        .sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount));
    
    if (incomeCategories.length === 0) {
        ctx.style.display = 'none';
        return;
    }
    
    ctx.style.display = 'block';
    
    const labels = incomeCategories.map(c => c.category_name);
    const amounts = incomeCategories.map(c => Math.abs(c.amount));
    
    charts.incomeCategories = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Amount (€)',
                data: amounts,
                backgroundColor: 'rgba(34, 197, 94, 0.8)', // Green for income
                borderColor: 'rgb(34, 197, 94)',
                borderWidth: 1
            }]
        },
        options: {
            indexAxis: 'y', // Horizontal bars
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                title: {
                    display: true,
                    text: `Income Categories (${dateRange})`
                },
                legend: {
                    display: false
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const category = incomeCategories[context.dataIndex];
                            return [
                                `€${context.parsed.x.toLocaleString()}`,
                                `${category.transaction_count} transactions`
                            ];
                        }
                    }
                }
            },
            scales: {
                x: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Amount (€)'
                    },
                    ticks: {
                        callback: function(value) {
                            return '€' + value.toLocaleString();
                        }
                    }
                },
                y: {
                    title: {
                        display: true,
                        text: 'Categories'
                    }
                }
            }
        }
    });
}

/**
 * Create horizontal bar chart for saving categories
 */
function updateSavingCategoriesChart(data) {
    const ctx = document.getElementById('saving-categories-chart');
    if (!ctx) return;

    // Destroy existing chart
    if (charts.savingCategories) {
        charts.savingCategories.destroy();
    }

    const categories = data.categories || [];
    const dateRange = formatDateRange(data.start_date, data.end_date, data.year);
    
    // Get all saving categories, sorted by amount (descending)
    const savingCategories = categories
        .filter(c => c.category_type === 'saving')
        .sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount));
    
    if (savingCategories.length === 0) {
        ctx.style.display = 'none';
        return;
    }
    
    ctx.style.display = 'block';
    
    const labels = savingCategories.map(c => c.category_name);
    const amounts = savingCategories.map(c => Math.abs(c.amount));
    
    charts.savingCategories = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Amount (€)',
                data: amounts,
                backgroundColor: 'rgba(59, 130, 246, 0.8)', // Blue for saving
                borderColor: 'rgb(59, 130, 246)',
                borderWidth: 1
            }]
        },
        options: {
            indexAxis: 'y', // Horizontal bars
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                title: {
                    display: true,
                    text: `Saving Categories (${dateRange})`
                },
                legend: {
                    display: false
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const category = savingCategories[context.dataIndex];
                            return [
                                `€${context.parsed.x.toLocaleString()}`,
                                `${category.transaction_count} transactions`
                            ];
                        }
                    }
                }
            },
            scales: {
                x: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Amount (€)'
                    },
                    ticks: {
                        callback: function(value) {
                            return '€' + value.toLocaleString();
                        }
                    }
                },
                y: {
                    title: {
                        display: true,
                        text: 'Categories'
                    }
                }
            }
        }
    });
}

/**
 * Update all category charts
 */
function updateCategoryBreakdownChart(data) {
    updateSpendingCategoriesChart(data);
    updateIncomeCategoriesChart(data);
    updateSavingCategoriesChart(data);
}

/**
 * Initialize or update savings tracking chart
 */
function updateSavingsTrackingChart(data) {
    const ctx = document.getElementById('savings-tracking-chart');
    if (!ctx) return;

    // Destroy existing chart
    if (charts.savingsTracking) {
        charts.savingsTracking.destroy();
    }

    const savingsData = data.monthly_savings || [];
    const dateRange = formatDateRange(data.start_date, data.end_date, data.year);
    
    // Prepare chart data for line chart showing savings trends - handle empty data case
    let labels, monthlyValues, cumulativeValues;
    if (savingsData.length === 0) {
        labels = ['No Data'];
        monthlyValues = [0];
        cumulativeValues = [0];
    } else {
        labels = savingsData.map(s => {
            const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
            return monthNames[parseInt(s.month) - 1];
        });
        monthlyValues = savingsData.map(s => Math.abs(s.amount));
        cumulativeValues = savingsData.map(s => s.cumulative_amount);
    }
    
    charts.savingsTracking = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Monthly Savings',
                    data: monthlyValues,
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    borderColor: 'rgb(59, 130, 246)',
                    borderWidth: 3,
                    fill: true,
                    tension: 0.1,
                    pointBackgroundColor: 'rgb(59, 130, 246)',
                    pointBorderColor: 'white',
                    pointBorderWidth: 2,
                    pointRadius: savingsData.length === 0 ? 0 : 5
                },
                {
                    label: 'Cumulative Savings',
                    data: cumulativeValues,
                    backgroundColor: 'rgba(34, 197, 94, 0.1)',
                    borderColor: 'rgb(34, 197, 94)',
                    borderWidth: 3,
                    fill: false,
                    tension: 0.1,
                    pointBackgroundColor: 'rgb(34, 197, 94)',
                    pointBorderColor: 'white',
                    pointBorderWidth: 2,
                    pointRadius: savingsData.length === 0 ? 0 : 5
                }
            ]
        },
        options: {
            responsive: true,
            plugins: {
                title: {
                    display: true,
                    text: `Savings Tracking (${dateRange})`
                },
                legend: {
                    display: true
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            if (savingsData.length === 0) {
                                return 'No savings data available for selected period';
                            }
                            const label = context.dataset.label || '';
                            const value = context.parsed.y;
                            return label + ': €' + value.toLocaleString();
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Amount (€)'
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

/**
 * Update top transactions chart (bar chart)
 */
function updateTopTransactionsChart(data) {
    const ctx = document.getElementById('top-transactions-chart');
    if (!ctx) return;

    // Destroy existing chart
    if (charts.topTransactions) {
        charts.topTransactions.destroy();
    }

    const transactions = data.transactions || [];
    
    if (transactions.length === 0) {
        return;
    }
    
    // Take top 10 transactions by absolute amount
    const topTransactions = transactions
        .sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount))
        .slice(0, 10);
    
    // Prepare chart data
    const labels = topTransactions.map(t => {
        // Truncate long descriptions
        const desc = t.description || t.name || 'Unknown';
        return desc.length > 20 ? desc.substring(0, 20) + '...' : desc;
    });
    const amounts = topTransactions.map(t => Math.abs(t.amount));
    
    charts.topTransactions = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Transaction Amount',
                data: amounts,
                backgroundColor: topTransactions.map(t => 
                    t.amount < 0 ? 'rgba(239, 68, 68, 0.8)' : 'rgba(34, 197, 94, 0.8)'
                ),
                borderColor: topTransactions.map(t => 
                    t.amount < 0 ? 'rgb(239, 68, 68)' : 'rgb(34, 197, 94)'
                ),
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            plugins: {
                title: {
                    display: true,
                    text: 'Top Transactions by Amount'
                },
                legend: {
                    display: false
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const transaction = topTransactions[context.dataIndex];
                            return [
                                `Amount: €${Math.abs(transaction.amount).toLocaleString()}`,
                                `Date: ${new Date(transaction.date).toLocaleDateString()}`,
                                `Category: ${transaction.category || 'Uncategorized'}`
                            ];
                        }
                    }
                }
            },
            scales: {
                x: {
                    ticks: {
                        maxRotation: 45,
                        minRotation: 0
                    }
                },
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Amount (€)'
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

/**
 * Update dashboard year selector and refresh all charts
 */
function updateDashboardYear() {
    const yearSelector = document.getElementById('global-year-selector');
    if (!yearSelector) return;
    
    const selectedYear = yearSelector.value;
    
    // Update all chart sections with new year
    const sections = [
        'budget-variance-container',
        'monthly-overview-container', 
        'category-breakdown-container',
        'savings-tracking-container'
    ];
    
    sections.forEach(sectionId => {
        const container = document.getElementById(sectionId);
        if (container) {
            // Trigger HTMX reload with new year parameter
            const endpoint = container.getAttribute('hx-get');
            if (endpoint) {
                const url = new URL(endpoint, window.location.origin);
                url.searchParams.set('year', selectedYear);
                container.setAttribute('hx-get', url.toString());
                htmx.trigger(container, 'htmx:trigger');
            }
        }
    });
}

/**
 * Update top transactions for selected month
 */
function updateTopTransactions() {
    const monthSelector = document.getElementById('month-selector');
    const yearSelector = document.getElementById('global-year-selector');
    
    if (!monthSelector || !yearSelector) return;
    
    const selectedMonth = monthSelector.value;
    const selectedYear = yearSelector.value;
    
    const container = document.getElementById('top-transactions-container');
    if (container) {
        const endpoint = container.getAttribute('hx-get') || '/api/analytics/top-transactions';
        const url = new URL(endpoint, window.location.origin);
        url.searchParams.set('month', selectedMonth);
        url.searchParams.set('year', selectedYear);
        
        container.setAttribute('hx-get', url.toString());
        htmx.trigger(container, 'htmx:trigger');
    }
}

/**
 * Initialize year selector on page load
 */
function initializeYearSelector() {
    fetch('/api/analytics/available-years')
        .then(response => response.json())
        .then(data => {
            const yearSelector = document.getElementById('global-year-selector');
            if (!yearSelector) return;
            
            const years = data.years || [];
            const currentYear = data.current_year || new Date().getFullYear();
            
            yearSelector.innerHTML = '';
            
            // If no years available, add current year as fallback
            if (years.length === 0) {
                const option = document.createElement('option');
                option.value = currentYear;
                option.textContent = currentYear;
                option.selected = true;
                yearSelector.appendChild(option);
            } else {
                years.forEach(year => {
                    const option = document.createElement('option');
                    option.value = year;
                    option.textContent = year;
                    if (year === currentYear) {
                        option.selected = true;
                    }
                    yearSelector.appendChild(option);
                });
            }
            
            // Set current month in month selector
            const monthSelector = document.getElementById('month-selector');
            if (monthSelector) {
                const currentMonth = new Date().getMonth() + 1;
                monthSelector.value = currentMonth.toString();
            }
        })
        .catch(error => {
            console.error('Error loading available years:', error);
            
            // Fallback: add current year manually
            const yearSelector = document.getElementById('global-year-selector');
            if (yearSelector) {
                const currentYear = new Date().getFullYear();
                yearSelector.innerHTML = '';
                const option = document.createElement('option');
                option.value = currentYear;
                option.textContent = currentYear;
                option.selected = true;
                yearSelector.appendChild(option);
            }
        });
}

/**
 * Update year-over-year comparison functionality
 */
function updateYearOverYearComparison() {
    const year1Selector = document.getElementById('yoy-year1-selector');
    const year2Selector = document.getElementById('yoy-year2-selector');
    const viewModeSelector = document.getElementById('yoy-view-mode');
    
    if (!year1Selector || !year2Selector || !viewModeSelector) return;
    
    const year1 = year1Selector.value;
    const year2 = year2Selector.value;
    const viewMode = viewModeSelector.value;
    
    if (!year1 || !year2) return;
    
    const container = document.getElementById('yoy-comparison-container');
    if (container) {
        const endpoint = '/api/analytics/year-over-year';
        const url = new URL(endpoint, window.location.origin);
        url.searchParams.set('years', `${year1},${year2}`);
        url.searchParams.set('view_mode', viewMode);
        
        fetch(url)
            .then(response => response.json())
            .then(data => {
                // Update comparison table
                updateYearOverYearTable(data, viewMode);
                
                // Update charts if functions exist (from analytics_yoy.js)
                if (typeof updateYearOverYearCharts === 'function') {
                    updateYearOverYearCharts(data, viewMode);
                }
            })
            .catch(error => {
                console.error('Error loading year-over-year data:', error);
            });
    }
}

/**
 * Update year-over-year comparison table
 */
function updateYearOverYearTable(data, viewMode) {
    const container = document.getElementById('yoy-comparison-table');
    if (!container) return;
    
    const categories = data.categories || [];
    const summary = data.summary || {};
    const years = summary.years || [];
    
    if (years.length < 2) {
        container.innerHTML = '<p class="text-red-500">Please select two different years for comparison.</p>';
        return;
    }
    
    let tableHtml = `
        <div class="overflow-x-auto">
            <table class="min-w-full bg-white border border-gray-200">
                <thead class="bg-gray-50">
                    <tr>
                        <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Category</th>
                        <th class="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">${years[0]}</th>
                        <th class="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">${years[1]}</th>
                        <th class="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Change</th>
                        <th class="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">% Change</th>
                    </tr>
                </thead>
                <tbody class="bg-white divide-y divide-gray-200">
    `;
    
    categories.forEach(category => {
        const year1Data = category.yearly_data[years[0]] || {};
        const year2Data = category.yearly_data[years[1]] || {};
        
        const year1Value = viewMode === 'monthly_avg' ? year1Data.monthly_avg : year1Data.total;
        const year2Value = viewMode === 'monthly_avg' ? year2Data.monthly_avg : year2Data.total;
        
        const changeKey = `${years[0]}_to_${years[1]}`;
        const change = category.changes[changeKey] || {};
        
        const absoluteChange = viewMode === 'monthly_avg' ? change.absolute_monthly : change.absolute_total;
        const percentageChange = viewMode === 'monthly_avg' ? change.percentage_monthly : change.percentage_total;
        
        const changeClass = absoluteChange >= 0 ? 'text-red-600' : 'text-green-600';
        const changeSymbol = absoluteChange >= 0 ? '+' : '';
        
        tableHtml += `
            <tr>
                <td class="px-4 py-2 text-sm font-medium text-gray-900">${category.name}</td>
                <td class="px-4 py-2 text-sm text-gray-900 text-right">€${Math.abs(year1Value || 0).toLocaleString()}</td>
                <td class="px-4 py-2 text-sm text-gray-900 text-right">€${Math.abs(year2Value || 0).toLocaleString()}</td>
                <td class="px-4 py-2 text-sm ${changeClass} text-right">${changeSymbol}€${Math.abs(absoluteChange || 0).toLocaleString()}</td>
                <td class="px-4 py-2 text-sm ${changeClass} text-right">${changeSymbol}${(percentageChange || 0).toFixed(1)}%</td>
            </tr>
        `;
    });
    
    tableHtml += `
                </tbody>
            </table>
        </div>
    `;
    
    container.innerHTML = tableHtml;
}

/**
 * Update cumulative category chart
 */
function updateCategoryCumulativeChart() {
    const categorySelector = document.getElementById('cumulative-category-selector');
    if (!categorySelector) return;
    
    const selectedCategory = categorySelector.value;
    if (!selectedCategory) return;
    
    const year1Selector = document.getElementById('yoy-year1-selector');
    const year2Selector = document.getElementById('yoy-year2-selector');
    
    if (!year1Selector || !year2Selector) return;
    
    const year1 = year1Selector.value;
    const year2 = year2Selector.value;
    
    const years = [year1, year2].filter(y => y);
    if (years.length === 0) return;
    
    const endpoint = '/api/analytics/category-cumulative';
    const url = new URL(endpoint, window.location.origin);
    url.searchParams.set('category', selectedCategory);
    url.searchParams.set('years', years.join(','));
    
    fetch(url)
        .then(response => response.json())
        .then(data => {
            if (typeof updateCategoryCumulativeChartDisplay === 'function') {
                updateCategoryCumulativeChartDisplay(data);
            }
        })
        .catch(error => {
            console.error('Error loading cumulative category data:', error);
        });
}

/**
 * Update category analysis with selected filters
 */
function updateCategoryAnalysis() {
    const startDate = document.getElementById('start-date').value;
    const endDate = document.getElementById('end-date').value;
    const categoryType = document.getElementById('category-type').value;
    
    // Build URL with parameters
    const url = new URL('/api/analytics/category-breakdown', window.location.origin);
    if (startDate) url.searchParams.set('start_date', startDate);
    if (endDate) url.searchParams.set('end_date', endDate);
    if (categoryType) url.searchParams.set('category_type', categoryType);
    
    fetch(url)
        .then(response => response.json())
        .then(data => {
            // Update the container with success message
            const container = document.getElementById('category-breakdown-container');
            if (container) {
                container.innerHTML = '<div class="text-green-600">Category analysis updated. Check chart below.</div>';
            }
            
            // Update the chart
            updateCategoryBreakdownChart(data);
        })
        .catch(error => {
            console.error('Error loading category breakdown data:', error);
            const container = document.getElementById('category-breakdown-container');
            if (container) {
                container.innerHTML = '<div class="text-red-600">Error loading category data: ' + error.message + '</div>';
            }
        });
}

/**
 * Handle quick month selection buttons
 */
function handleQuickMonthSelection() {
    // Add event listeners to quick month buttons
    const quickMonthButtons = document.querySelectorAll('.quick-month-btn');
    const currentYear = new Date().getFullYear();
    
    quickMonthButtons.forEach(button => {
        button.addEventListener('click', function() {
            const month = parseInt(this.dataset.month);
            
            // Calculate start and end dates for the month
            const startDate = new Date(currentYear, month - 1, 1);
            const endDate = new Date(currentYear, month, 0); // Last day of month
            
            // Set the date inputs
            document.getElementById('start-date').value = startDate.toISOString().split('T')[0];
            document.getElementById('end-date').value = endDate.toISOString().split('T')[0];
            
            // Update button styling
            quickMonthButtons.forEach(btn => btn.classList.remove('bg-blue-500', 'text-white'));
            quickMonthButtons.forEach(btn => btn.classList.add('bg-gray-200'));
            this.classList.remove('bg-gray-200');
            this.classList.add('bg-blue-500', 'text-white');
            
            // Auto-update the analysis
            updateCategoryAnalysis();
        });
    });
}

// Initialize everything when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    initializeYearSelector();
    handleQuickMonthSelection();
    
    // Load initial category breakdown chart
    updateCategoryAnalysis();
});