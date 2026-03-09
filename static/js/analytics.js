/**
 * Analytics JavaScript for FafyCat financial analytics
 * Handles Chart.js initialization and HTMX integration
 */

function toRgba(hex, alpha) {
    if (!hex || hex.length < 7) return `rgba(128, 128, 128, ${alpha})`;
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

const THEME = {};
function loadThemeColors() {
    const style = getComputedStyle(document.documentElement);
    THEME.spending = style.getPropertyValue('--color-spending').trim();
    THEME.income = style.getPropertyValue('--color-income').trim();
    THEME.saving = style.getPropertyValue('--color-saving').trim();
    THEME.success = style.getPropertyValue('--color-success').trim();
    THEME.error = style.getPropertyValue('--color-error').trim();
    THEME.purple = style.getPropertyValue('--color-purple').trim();
    THEME.amber = style.getPropertyValue('--color-amber').trim();
    THEME.bgPrimary = style.getPropertyValue('--bg-primary').trim();
    THEME.bgHover = style.getPropertyValue('--bg-hover').trim();
    THEME.textPrimary = style.getPropertyValue('--text-primary').trim();
    THEME.textSecondary = style.getPropertyValue('--text-secondary').trim();
    THEME.borderSubtle = style.getPropertyValue('--border-subtle').trim();
    THEME.borderDefault = style.getPropertyValue('--border-default').trim();
}
window.THEME = THEME;

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
 * Initialize Chart.js theme defaults for Bauhaus dark mode
 */
function initChartTheme() {
    Chart.defaults.color = THEME.textSecondary;
    Chart.defaults.borderColor = THEME.borderSubtle;
    Chart.defaults.font.family = "'DM Sans', sans-serif";
    Chart.defaults.plugins.title.font = { family: "'Syne', sans-serif", weight: 600 };
    Chart.defaults.plugins.tooltip.backgroundColor = THEME.bgHover;
    Chart.defaults.plugins.tooltip.titleColor = THEME.textPrimary;
    Chart.defaults.plugins.tooltip.bodyColor = THEME.textSecondary;
    Chart.defaults.plugins.tooltip.borderColor = THEME.borderDefault;
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.scale.grid = { color: THEME.borderSubtle, drawBorder: false };
}

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
                    backgroundColor: toRgba(THEME.saving, 0.7),
                    borderColor: THEME.saving,
                    borderWidth: 1
                },
                {
                    label: 'Actual',
                    data: actualData,
                    backgroundColor: variances.map(v =>
                        v.is_overspent ? toRgba(THEME.spending, 0.7) : toRgba(THEME.success, 0.7)
                    ),
                    borderColor: variances.map(v =>
                        v.is_overspent ? THEME.spending : THEME.success
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
                    backgroundColor: toRgba(THEME.income, 0.8),
                    borderColor: THEME.income,
                    borderWidth: 1,
                    stack: 'flow'
                },
                {
                    label: 'Spending',
                    data: monthlyData.map(m => -Math.abs(m.spending)),
                    backgroundColor: toRgba(THEME.spending, 0.8),
                    borderColor: THEME.spending,
                    borderWidth: 1,
                    stack: 'flow'
                },
                {
                    label: 'Saving',
                    data: monthlyData.map(m => -Math.abs(m.saving)),
                    backgroundColor: toRgba(THEME.saving, 0.8),
                    borderColor: THEME.saving,
                    borderWidth: 1,
                    stack: 'flow'
                },
                {
                    label: 'Profit/Loss',
                    data: monthlyData.map(m => m.profit_loss),
                    type: 'line',
                    backgroundColor: toRgba(THEME.purple, 0.1),
                    borderColor: THEME.purple,
                    borderWidth: 3,
                    fill: false,
                    yAxisID: 'y1',
                    pointBackgroundColor: monthlyData.map(m =>
                        m.profit_loss >= 0 ? THEME.success : THEME.spending
                    ),
                    pointBorderColor: THEME.purple,
                    pointRadius: 5
                },
                {
                    label: 'Cumulative Profit/Loss',
                    data: monthlyData.map(m => m.cumulative_profit_loss),
                    type: 'line',
                    backgroundColor: toRgba(THEME.amber, 0.1),
                    borderColor: THEME.amber,
                    borderWidth: 2,
                    borderDash: [5, 5],
                    fill: false,
                    yAxisID: 'y1',
                    pointBackgroundColor: THEME.amber,
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
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6 p-4 rounded-lg">
            <div class="text-center">
                <div class="text-lg font-bold" style="color: var(--color-income)">€${avgMonthlyIncome.toLocaleString()}</div>
                <div class="text-sm" title="Average monthly income across months with income transactions">Avg Monthly Income</div>
            </div>
            <div class="text-center">
                <div class="text-lg font-bold" style="color: var(--color-spending)">€${avgMonthlySpending.toLocaleString()}</div>
                <div class="text-sm" title="Average monthly spending across months with spending transactions">Avg Monthly Spending</div>
            </div>
            <div class="text-center">
                <div class="text-lg font-bold" style="color: var(--color-saving)">${savingsRate.toFixed(1)}%</div>
                <div class="text-sm" title="Percentage of income that was saved (savings / income × 100)">Savings Rate</div>
            </div>
            <div class="text-center">
                <div class="text-lg font-bold ${yearlyTotals.profit_loss >= 0 ? 'amount-positive' : 'amount-negative'}">
                    €${yearlyTotals.profit_loss?.toLocaleString() || 0}
                </div>
                <div class="text-sm" title="Total income minus total spending (income - spending)">Net Profit/Loss</div>
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
                backgroundColor: toRgba(THEME.spending, 0.8),
                borderColor: THEME.spending,
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
                backgroundColor: toRgba(THEME.income, 0.8),
                borderColor: THEME.income,
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
                backgroundColor: toRgba(THEME.saving, 0.8),
                borderColor: THEME.saving,
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
                    backgroundColor: toRgba(THEME.saving, 0.1),
                    borderColor: THEME.saving,
                    borderWidth: 3,
                    fill: true,
                    tension: 0.1,
                    pointBackgroundColor: THEME.saving,
                    pointBorderColor: THEME.bgPrimary,
                    pointBorderWidth: 2,
                    pointRadius: savingsData.length === 0 ? 0 : 5
                },
                {
                    label: 'Cumulative Savings',
                    data: cumulativeValues,
                    backgroundColor: toRgba(THEME.income, 0.1),
                    borderColor: THEME.income,
                    borderWidth: 3,
                    fill: false,
                    tension: 0.1,
                    pointBackgroundColor: THEME.income,
                    pointBorderColor: THEME.bgPrimary,
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

    const transactions = data.transactions || data.top_transactions || [];

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
                    t.amount < 0 ? toRgba(THEME.spending, 0.8) : toRgba(THEME.income, 0.8)
                ),
                borderColor: topTransactions.map(t =>
                    t.amount < 0 ? THEME.spending : THEME.income
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
