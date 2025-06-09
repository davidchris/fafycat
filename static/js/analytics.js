/**
 * Analytics JavaScript for FafyCat financial analytics
 * Handles Chart.js initialization and HTMX integration
 */

// Chart instances storage
let charts = {
    budgetVariance: null,
    monthlyOverview: null,
    categoryBreakdown: null,
    savingsTracking: null,
    topTransactions: null
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
 * Initialize or update category breakdown chart with enhanced features
 */
function updateCategoryBreakdownChart(data) {
    const ctx = document.getElementById('category-breakdown-chart');
    if (!ctx) return;

    // Destroy existing chart
    if (charts.categoryBreakdown) {
        charts.categoryBreakdown.destroy();
    }

    const categories = data.categories || [];
    const dateRange = formatDateRange(data.start_date, data.end_date, data.year);
    
    // Separate spending categories and show top 8 for readability
    const spendingCategories = categories.filter(c => c.category_type === 'spending').slice(0, 8);
    const incomeCategories = categories.filter(c => c.category_type === 'income').slice(0, 3);
    const savingCategories = categories.filter(c => c.category_type === 'saving').slice(0, 3);
    
    // Check if we have data
    if (categories.length === 0) {
        ctx.getContext('2d').clearRect(0, 0, ctx.width, ctx.height);
        return;
    }
    
    // Determine chart type based on data
    const useHorizontalBar = spendingCategories.length > 5;
    
    if (useHorizontalBar) {
        // Horizontal bar chart for many categories
        charts.categoryBreakdown = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: spendingCategories.map(c => c.category_name),
                datasets: [{
                    label: 'Amount Spent',
                    data: spendingCategories.map(c => Math.abs(c.amount)),
                    backgroundColor: spendingCategories.map((c, i) => {
                        const colors = [
                            'rgba(239, 68, 68, 0.8)', 'rgba(245, 158, 11, 0.8)', 'rgba(59, 130, 246, 0.8)',
                            'rgba(168, 85, 247, 0.8)', 'rgba(236, 72, 153, 0.8)', 'rgba(14, 165, 233, 0.8)',
                            'rgba(34, 197, 94, 0.8)', 'rgba(156, 163, 175, 0.8)'
                        ];
                        return c.budget_variance < 0 ? 'rgba(239, 68, 68, 0.8)' : colors[i % colors.length];
                    }),
                    borderColor: spendingCategories.map(c => 
                        c.budget_variance < 0 ? 'rgb(239, 68, 68)' : 'rgb(59, 130, 246)'
                    ),
                    borderWidth: 2
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                plugins: {
                    title: {
                        display: true,
                        text: `Top Spending Categories (${dateRange})`,
                        font: { size: 14 }
                    },
                    legend: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const category = spendingCategories[context.dataIndex];
                                const amount = context.parsed.x;
                                const budget = category.budget || 0;
                                const variance = budget - amount;
                                
                                return [
                                    `Spent: €${amount.toLocaleString()}`,
                                    `Budget: €${budget.toLocaleString()}`,
                                    `Variance: €${variance.toFixed(0)} ${variance < 0 ? '(over)' : '(under)'}`
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
    } else {
        // Doughnut chart for fewer categories
        const topCategories = categories.slice(0, 8);
        const labels = topCategories.map(c => c.category_name);
        const amounts = topCategories.map(c => Math.abs(c.amount));
        
        // Generate colors based on category type
        const colors = topCategories.map(c => {
            if (c.category_type === 'income') return 'rgba(34, 197, 94, 0.7)';
            if (c.category_type === 'saving') return 'rgba(59, 130, 246, 0.7)';
            // Spending - use red for over budget, blue for under budget
            return c.budget_variance < 0 ? 'rgba(239, 68, 68, 0.7)' : 'rgba(245, 158, 11, 0.7)';
        });
        
        charts.categoryBreakdown = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: amounts,
                    backgroundColor: colors,
                    borderColor: colors.map(c => c.replace('0.7', '1')),
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    title: {
                        display: true,
                        text: `Category Breakdown (${dateRange})`,
                        font: { size: 14 }
                    },
                    legend: {
                        display: true,
                        position: 'bottom',
                        labels: {
                            generateLabels: function(chart) {
                                const data = chart.data;
                                return data.labels.map((label, i) => {
                                    const category = topCategories[i];
                                    const amount = data.datasets[0].data[i];
                                    const percentage = ((amount / amounts.reduce((a, b) => a + b, 0)) * 100).toFixed(1);
                                    
                                    return {
                                        text: `${label} (€${amount.toLocaleString()}, ${percentage}%)`,
                                        fillStyle: data.datasets[0].backgroundColor[i],
                                        strokeStyle: data.datasets[0].borderColor[i],
                                        lineWidth: data.datasets[0].borderWidth,
                                        hidden: false,
                                        index: i
                                    };
                                });
                            }
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const category = topCategories[context.dataIndex];
                                const amount = context.parsed;
                                const percentage = ((amount / amounts.reduce((a, b) => a + b, 0)) * 100).toFixed(1);
                                
                                return [
                                    `${category.category_name}: €${amount.toLocaleString()} (${percentage}%)`,
                                    `Type: ${category.category_type}`,
                                    category.budget_variance !== null ? 
                                        `Budget variance: €${category.budget_variance.toFixed(0)}` : ''
                                ].filter(Boolean);
                            }
                        }
                    }
                }
            }
        });
    }
    
    // Update category summary
    updateCategorySummary(data);
}

/**
 * Update category analysis summary
 */
function updateCategorySummary(data) {
    const categories = data.categories || [];
    const summary = data.summary || {};
    
    // Calculate category statistics
    const spendingCategories = categories.filter(c => c.category_type === 'spending');
    const incomeCategories = categories.filter(c => c.category_type === 'income');
    const savingCategories = categories.filter(c => c.category_type === 'saving');
    
    const topSpendingCategory = spendingCategories[0];
    const overBudgetCount = spendingCategories.filter(c => c.budget_variance < 0).length;
    
    const summaryHtml = `
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mt-6 p-4 bg-gray-50 rounded-lg">
            <div class="text-center">
                <div class="text-lg font-bold text-blue-600">${categories.length}</div>
                <div class="text-sm text-gray-600" title="Number of categories with transactions in the selected period">Active Categories</div>
            </div>
            <div class="text-center">
                <div class="text-lg font-bold ${overBudgetCount > 0 ? 'text-red-600' : 'text-green-600'}">
                    ${overBudgetCount}
                </div>
                <div class="text-sm text-gray-600" title="Number of spending categories that exceeded their budget">Over Budget</div>
            </div>
            <div class="text-center">
                <div class="text-lg font-bold text-gray-700">
                    ${topSpendingCategory ? topSpendingCategory.category_name : 'N/A'}
                </div>
                <div class="text-sm text-gray-600" title="Category with the highest total spending amount">Top Spending</div>
            </div>
        </div>
    `;
    
    // Find or create summary container
    let summaryContainer = document.getElementById('category-summary-container');
    if (!summaryContainer) {
        summaryContainer = document.createElement('div');
        summaryContainer.id = 'category-summary-container';
        const chartContainer = document.getElementById('category-breakdown-chart').parentNode;
        chartContainer.appendChild(summaryContainer);
    }
    summaryContainer.innerHTML = summaryHtml;
}

/**
 * Initialize or update enhanced savings tracking chart
 */
function updateSavingsTrackingChart(data) {
    const ctx = document.getElementById('savings-tracking-chart');
    if (!ctx) return;

    // Destroy existing chart
    if (charts.savingsTracking) {
        charts.savingsTracking.destroy();
    }

    const monthlySavings = data.monthly_savings || [];
    const statistics = data.statistics || {};
    const dateRange = formatDateRange(data.start_date, data.end_date, data.year);
    
    // Prepare chart data
    const labels = monthlySavings.map(m => {
        const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                           'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        return monthNames[parseInt(m.month) - 1];
    });
    
    // Calculate target line (median monthly savings extended)
    const medianSavings = statistics.median_monthly || 0;
    const targetCumulative = labels.map((_, i) => medianSavings * (i + 1));
    
    charts.savingsTracking = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Monthly Savings',
                    data: monthlySavings.map(m => m.amount),
                    backgroundColor: 'rgba(59, 130, 246, 0.2)',
                    borderColor: 'rgb(59, 130, 246)',
                    borderWidth: 3,
                    fill: true,
                    type: 'bar',
                    yAxisID: 'y',
                    order: 3
                },
                {
                    label: 'Cumulative Savings',
                    data: monthlySavings.map(m => m.cumulative_amount),
                    backgroundColor: 'rgba(34, 197, 94, 0.1)',
                    borderColor: 'rgb(34, 197, 94)',
                    borderWidth: 3,
                    fill: false,
                    yAxisID: 'y1',
                    pointBackgroundColor: 'rgb(34, 197, 94)',
                    pointBorderColor: 'white',
                    pointBorderWidth: 2,
                    pointRadius: 5,
                    order: 1
                },
                {
                    label: 'Target (Median Pace)',
                    data: targetCumulative,
                    backgroundColor: 'rgba(245, 158, 11, 0.1)',
                    borderColor: 'rgb(245, 158, 11)',
                    borderWidth: 2,
                    borderDash: [5, 5],
                    fill: false,
                    yAxisID: 'y1',
                    pointRadius: 0,
                    order: 2
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
                    text: `Savings Tracking (${dateRange})`,
                    font: { size: 16 }
                },
                legend: {
                    display: true,
                    position: 'bottom'
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const datasetLabel = context.dataset.label;
                            const value = context.parsed.y;
                            
                            if (datasetLabel === 'Monthly Savings') {
                                return `${datasetLabel}: €${value.toLocaleString()}`;
                            } else {
                                return `${datasetLabel}: €${value.toLocaleString()}`;
                            }
                        },
                        afterBody: function(tooltipItems) {
                            const monthIndex = tooltipItems[0].dataIndex;
                            const monthData = monthlySavings[monthIndex];
                            if (!monthData) return [];
                            
                            const target = targetCumulative[monthIndex];
                            const actual = monthData.cumulative_amount;
                            const variance = actual - target;
                            
                            return [
                                '',
                                `Progress vs Target: €${variance.toFixed(0)} ${variance >= 0 ? 'ahead' : 'behind'}`
                            ];
                        }
                    }
                }
            },
            scales: {
                y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Monthly Savings (€)'
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
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Cumulative Savings (€)'
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
    
    // Update savings statistics
    updateSavingsStatistics(data);
}

/**
 * Update savings statistics display
 */
function updateSavingsStatistics(data) {
    const statistics = data.statistics || {};
    const monthlySavings = data.monthly_savings || [];
    
    // Calculate additional metrics
    const currentMonth = new Date().getMonth() + 1;
    const monthsElapsed = currentMonth;
    const projectedYearEnd = statistics.median_monthly * 12;
    const currentPace = statistics.total_savings;
    const onTrackPercentage = monthsElapsed > 0 ? (currentPace / (statistics.median_monthly * monthsElapsed)) * 100 : 0;
    
    const statsHtml = `
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6 p-4 bg-gray-50 rounded-lg">
            <div class="text-center">
                <div class="text-lg font-bold text-blue-600">€${statistics.total_savings?.toLocaleString() || 0}</div>
                <div class="text-sm text-gray-600" title="Total amount saved across all months">Total Saved</div>
            </div>
            <div class="text-center">
                <div class="text-lg font-bold text-green-600">€${statistics.median_monthly?.toLocaleString() || 0}</div>
                <div class="text-sm text-gray-600" title="Middle value of monthly savings amounts (50th percentile)">Median Monthly</div>
            </div>
            <div class="text-center">
                <div class="text-lg font-bold text-purple-600">${statistics.months_with_savings || 0}</div>
                <div class="text-sm text-gray-600" title="Number of months that had savings transactions">Active Months</div>
            </div>
            <div class="text-center">
                <div class="text-lg font-bold ${onTrackPercentage >= 100 ? 'text-green-600' : onTrackPercentage >= 80 ? 'text-yellow-600' : 'text-red-600'}">
                    ${onTrackPercentage.toFixed(0)}%
                </div>
                <div class="text-sm text-gray-600" title="How well you're staying on track with your typical savings pace">On Track</div>
            </div>
        </div>
        
        <div class="mt-4 p-3 bg-blue-50 rounded-lg">
            <div class="text-sm text-blue-800">
                <strong>Projection:</strong> At current median pace (€${statistics.median_monthly?.toLocaleString() || 0}/month), 
                you're projected to save €${projectedYearEnd.toLocaleString()} by year-end.
            </div>
        </div>
    `;
    
    // Find or create stats container
    let statsContainer = document.getElementById('savings-stats-container');
    if (!statsContainer) {
        statsContainer = document.createElement('div');
        statsContainer.id = 'savings-stats-container';
        const chartContainer = document.getElementById('savings-tracking-chart').parentNode;
        chartContainer.appendChild(statsContainer);
    }
    statsContainer.innerHTML = statsHtml;
}

/**
 * HTMX event handlers for analytics data updates
 */
document.addEventListener('htmx:afterRequest', function(event) {
    const url = event.detail.requestConfig.url;
    
    try {
        const response = JSON.parse(event.detail.xhr.responseText);
        
        if (url.includes('/budget-variance')) {
            updateBudgetVarianceChart(response);
        } else if (url.includes('/monthly-summary')) {
            updateMonthlyOverviewChart(response);
        } else if (url.includes('/category-breakdown')) {
            updateCategoryBreakdownChart(response);
        } else if (url.includes('/savings-tracking')) {
            updateSavingsTrackingChart(response);
        }
    } catch (error) {
        console.warn('Could not parse analytics response:', error);
    }
});

/**
 * Set default date values on page load
 */
document.addEventListener('DOMContentLoaded', function() {
    // Set default dates to current month
    const today = new Date();
    const firstDay = new Date(today.getFullYear(), today.getMonth(), 1);
    
    const startDateInput = document.getElementById('start-date');
    const endDateInput = document.getElementById('end-date');
    
    if (startDateInput) {
        startDateInput.value = firstDay.toISOString().split('T')[0];
    }
    
    if (endDateInput) {
        endDateInput.value = today.toISOString().split('T')[0];
    }
    
    // Set year selector to current year
    const yearSelector = document.getElementById('year-selector');
    if (yearSelector) {
        yearSelector.value = today.getFullYear().toString();
    }
});

/**
 * Initialize or update top transactions chart
 */
function updateTopTransactionsChart(data) {
    const ctx = document.getElementById('top-transactions-chart');
    if (!ctx) return;

    // Destroy existing chart
    if (charts.topTransactions) {
        charts.topTransactions.destroy();
    }

    const transactions = data.top_transactions || [];
    
    if (transactions.length === 0) {
        ctx.style.display = 'none';
        return;
    }
    
    ctx.style.display = 'block';
    
    // Prepare chart data
    const labels = transactions.map(t => t.description.length > 30 ? t.description.substring(0, 30) + '...' : t.description);
    const amounts = transactions.map(t => t.amount);
    const percentages = transactions.map(t => t.percentage_of_total);
    
    // Generate colors
    const colors = [
        'rgba(239, 68, 68, 0.8)',   // Red
        'rgba(245, 158, 11, 0.8)',  // Amber
        'rgba(34, 197, 94, 0.8)',   // Green
        'rgba(59, 130, 246, 0.8)',  // Blue
        'rgba(147, 51, 234, 0.8)'   // Purple
    ];
    
    charts.topTransactions = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Amount (€)',
                data: amounts,
                backgroundColor: colors.slice(0, transactions.length),
                borderColor: colors.slice(0, transactions.length).map(color => color.replace('0.8', '1')),
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            plugins: {
                title: {
                    display: true,
                    text: `Top ${transactions.length} Spending Transactions - ${data.month_name} ${data.year}`,
                    font: { size: 16 }
                },
                legend: {
                    display: false
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const transaction = transactions[context.dataIndex];
                            return [
                                `Amount: €${transaction.amount.toLocaleString()}`,
                                `Category: ${transaction.category}`,
                                `${transaction.percentage_of_total.toFixed(1)}% of total spending`
                            ];
                        },
                        title: function(context) {
                            const transaction = transactions[context[0].dataIndex];
                            return transaction.description;
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
                },
                x: {
                    title: {
                        display: true,
                        text: 'Transactions'
                    },
                    ticks: {
                        maxRotation: 45,
                        minRotation: 0
                    }
                }
            }
        }
    });
}