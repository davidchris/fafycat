/**
 * Year-over-Year Analytics JavaScript for FafyCat
 * Handles year-over-year comparison charts and cumulative category charts
 */

// Uses shared THEME and toRgba from analytics.js

/**
 * Update year-over-year comparison charts
 */
function updateYearOverYearCharts(data, viewMode) {
    const categories = data.categories || [];
    const years = data.summary.years || [];

    if (categories.length === 0 || years.length === 0) {
        // Hide charts if no data
        document.getElementById('yoy-comparison-chart').style.display = 'none';
        document.getElementById('yoy-cumulative-chart').style.display = 'none';
        return;
    }

    // Show comparison chart
    document.getElementById('yoy-comparison-chart').style.display = 'block';

    // Update grouped bar chart
    updateYearOverYearBarChart(data, viewMode);

    // Update cumulative chart if a category is selected
    const selectedCategory = document.getElementById('cumulative-category-selector').value;
    if (selectedCategory) {
        updateCategoryCumulativeChart();
    }
}

/**
 * Update year-over-year grouped bar chart
 */
function updateYearOverYearBarChart(data, viewMode) {
    const ctx = document.getElementById('yoy-comparison-chart');
    if (!ctx) return;

    // Destroy existing chart
    if (charts.yearOverYear) {
        charts.yearOverYear.destroy();
    }

    const categories = data.categories.slice(0, 10); // Top 10 categories
    const years = data.summary.years;

    // Prepare datasets for each year
    const datasets = years.map((year, index) => {
        const colors = [
            toRgba(window.THEME.saving, 0.85),
            toRgba(window.THEME.income, 0.85),
            toRgba(window.THEME.spending, 0.85),
            toRgba(window.THEME.purple, 0.85),
            toRgba(window.THEME.amber, 0.85)
        ];

        const borderColors = [
            window.THEME.saving,
            window.THEME.income,
            window.THEME.spending,
            window.THEME.purple,
            window.THEME.amber
        ];

        return {
            label: year.toString(),
            data: categories.map(cat => {
                const yearData = cat.yearly_data[year] || {};
                const value = viewMode === 'monthly_avg' ? yearData.monthly_avg : yearData.total;
                return Math.abs(value || 0);
            }),
            backgroundColor: colors[index % colors.length],
            borderColor: borderColors[index % borderColors.length],
            borderWidth: 2
        };
    });

    charts.yearOverYear = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: categories.map(c => c.name),
            datasets: datasets
        },
        options: {
            responsive: true,
            plugins: {
                title: {
                    display: true,
                    text: `Year-over-Year Category Comparison (${viewMode === 'monthly_avg' ? 'Monthly Average' : 'Total'})`,
                    font: { size: 16 }
                },
                legend: {
                    display: true,
                    position: 'top'
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const category = categories[context.dataIndex];
                            const year = years[context.datasetIndex];
                            const yearData = category.yearly_data[year] || {};
                            const value = viewMode === 'monthly_avg' ? yearData.monthly_avg : yearData.total;

                            const lines = [
                                `${year}: €${Math.abs(value || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`
                            ];

                            // Add change info if not the first year
                            if (context.datasetIndex > 0) {
                                const prevYear = years[context.datasetIndex - 1];
                                const changeKey = `${prevYear}_to_${year}`;
                                const change = category.changes[changeKey];

                                if (change) {
                                    const changeField = viewMode === 'monthly_avg' ? 'percentage_monthly' : 'percentage_total';
                                    const percentageChange = change[changeField];
                                    lines.push(`Change: ${percentageChange > 0 ? '+' : ''}${percentageChange.toFixed(1)}%`);
                                }
                            }

                            if (yearData.months_with_data && viewMode === 'monthly_avg') {
                                lines.push(`Based on ${yearData.months_with_data} months`);
                            }

                            return lines;
                        }
                    }
                }
            },
            scales: {
                x: {
                    title: {
                        display: true,
                        text: 'Categories'
                    },
                    ticks: {
                        maxRotation: 45,
                        minRotation: 0
                    }
                },
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: `Amount (€) - ${viewMode === 'monthly_avg' ? 'Monthly Average' : 'Total'}`
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
 * Update category cumulative chart display
 */
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
            window.THEME.saving,
            window.THEME.income,
            window.THEME.spending,
            window.THEME.purple,
            window.THEME.amber
        ];

        const yearData = monthlyData[year] || { cumulative: Array(12).fill(0) };

        return {
            label: year.toString(),
            data: yearData.cumulative.map(val => Math.abs(val)),
            borderColor: colors[index % colors.length],
            backgroundColor: toRgba(colors[index % colors.length], 0.1),
            borderWidth: 3,
            fill: false,
            tension: 0.1,
            pointBackgroundColor: colors[index % colors.length],
            pointBorderColor: window.THEME.bgPrimary,
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
