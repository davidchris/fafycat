/**
 * Analytics page controller.
 * Keeps API orchestration in one place and delegates chart drawing to analytics.js/analytics_yoy.js.
 */

(function() {
    'use strict';

    const sortState = {
        column: null,
        order: 'asc',
        currentData: null,
        currentViewMode: null
    };

    function pad2(value) {
        return String(value).padStart(2, '0');
    }

    function formatLocalDate(dateObj) {
        return `${dateObj.getFullYear()}-${pad2(dateObj.getMonth() + 1)}-${pad2(dateObj.getDate())}`;
    }

    function todayLocalISO() {
        return formatLocalDate(new Date());
    }

    function monthEndLocalISO(year, month) {
        const lastDay = new Date(year, month, 0).getDate();
        return `${year}-${pad2(month)}-${pad2(lastDay)}`;
    }

    function getYearSelection() {
        const yearSelector = document.getElementById('global-year-selector');
        const selectedYear = yearSelector ? yearSelector.value : 'ytd';
        const currentYear = new Date().getFullYear();

        if (selectedYear === 'ytd') {
            return {
                selectedYear,
                actualYear: currentYear,
                startDate: `${currentYear}-01-01`,
                endDate: todayLocalISO(),
                isYtd: true
            };
        }

        const actualYear = Number(selectedYear) || currentYear;
        return {
            selectedYear,
            actualYear,
            startDate: `${actualYear}-01-01`,
            endDate: `${actualYear}-12-31`,
            isYtd: false
        };
    }

    function setContainerMessage(containerId, message, isError = false) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const wrapper = document.createElement('div');
        wrapper.className = isError ? 'text-center py-8 amount-negative' : 'text-center py-8';
        wrapper.textContent = message;
        container.replaceChildren(wrapper);
    }

    async function fetchJson(url, context) {
        let response;
        try {
            response = await fetch(url);
        } catch (error) {
            throw new Error(`${context}: network error`);
        }

        if (!response.ok) {
            let detail = `HTTP ${response.status}`;
            try {
                const payload = await response.json();
                if (payload && payload.detail) {
                    detail = payload.detail;
                }
            } catch {
                // Ignore JSON parse errors and keep HTTP fallback detail.
            }
            throw new Error(`${context}: ${detail}`);
        }

        return response.json();
    }

    function syncCategoryDateInputsToYear() {
        const startInput = document.getElementById('start-date');
        const endInput = document.getElementById('end-date');
        if (!startInput || !endInput) return;

        const range = getYearSelection();
        startInput.value = range.startDate;
        endInput.value = range.endDate;
    }

    async function populateYearSelector() {
        const yearSelector = document.getElementById('global-year-selector');
        if (!yearSelector) return;

        let years = [];
        let currentYear = new Date().getFullYear();

        try {
            const data = await fetchJson('/api/analytics/available-years', 'Loading available years failed');
            years = Array.isArray(data.years) ? data.years : [];
            currentYear = Number(data.current_year) || currentYear;
        } catch (error) {
            console.error(error.message);
            years = [currentYear];
        }

        yearSelector.replaceChildren();

        const ytdOption = document.createElement('option');
        ytdOption.value = 'ytd';
        ytdOption.textContent = 'YTD (Year-to-Date)';
        ytdOption.selected = true;
        yearSelector.appendChild(ytdOption);

        const seen = new Set();
        years
            .map(year => Number(year))
            .filter(year => Number.isFinite(year))
            .sort((a, b) => b - a)
            .forEach(year => {
                if (seen.has(year)) return;
                seen.add(year);

                const option = document.createElement('option');
                option.value = String(year);
                option.textContent = String(year);
                yearSelector.appendChild(option);
            });
    }

    function formatCurrency(value) {
        return `€${Number(value || 0).toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        })}`;
    }

    function appendCell(row, text, className = '') {
        const cell = document.createElement('td');
        if (className) {
            cell.className = className;
        }
        cell.textContent = text;
        row.appendChild(cell);
    }

    function updateTopTransactionsDisplay(data) {
        const container = document.getElementById('top-transactions-container');
        if (!container) return;

        const transactions = Array.isArray(data.top_transactions) ? data.top_transactions : [];

        if (transactions.length === 0) {
            setContainerMessage(
                'top-transactions-container',
                `No transactions found for ${data.month_name || 'this month'} ${data.year || ''}`.trim()
            );
            return;
        }

        const fragment = document.createDocumentFragment();

        const summary = document.createElement('div');
        summary.className = 'mb-4';

        const heading = document.createElement('h3');
        heading.className = 'text-lg font-semibold';
        heading.textContent = `Top ${transactions.length} Spending Transactions - ${data.month_name} ${data.year}`;

        const total = document.createElement('p');
        total.className = 'text-sm text-secondary';
        total.textContent = `Total spending: ${formatCurrency(data.total_spending)}`;

        summary.append(heading, total);
        fragment.appendChild(summary);

        const tableContainer = document.createElement('div');
        tableContainer.className = 'table-container';

        const overflow = document.createElement('div');
        overflow.className = 'overflow-x-auto';

        const table = document.createElement('table');
        table.className = 'min-w-full';

        const thead = document.createElement('thead');
        const headRow = document.createElement('tr');
        ['Date', 'Description', 'Category', 'Amount', '% of Total'].forEach(label => {
            const th = document.createElement('th');
            th.textContent = label;
            headRow.appendChild(th);
        });
        thead.appendChild(headRow);

        const tbody = document.createElement('tbody');
        transactions.forEach(transaction => {
            const row = document.createElement('tr');
            const txDate = transaction.date ? new Date(transaction.date).toLocaleDateString() : 'N/A';
            const description = transaction.description || '';
            const category = transaction.category || 'Unknown';
            const percentage = Number(transaction.percentage_of_total || 0);

            appendCell(row, txDate, 'whitespace-nowrap');
            appendCell(row, description, '');
            appendCell(row, category, 'whitespace-nowrap');
            appendCell(row, formatCurrency(transaction.amount), 'text-right');
            appendCell(row, `${percentage.toFixed(1)}%`, 'text-right');

            tbody.appendChild(row);
        });

        table.append(thead, tbody);
        overflow.appendChild(table);
        tableContainer.appendChild(overflow);
        fragment.appendChild(tableContainer);

        container.replaceChildren(fragment);
    }

    async function updateTopTransactions() {
        const monthSelector = document.getElementById('month-selector');
        const selectedMonth = Number(monthSelector ? monthSelector.value : 1);
        const range = getYearSelection();

        const url = new URL('/api/analytics/top-transactions', window.location.origin);
        url.searchParams.set('year', String(range.actualYear));
        url.searchParams.set('month', String(selectedMonth));

        try {
            const data = await fetchJson(url.toString(), 'Loading top transactions failed');
            updateTopTransactionsDisplay(data);
            const chartTransactions = (data.top_transactions || []).map(transaction => ({
                ...transaction,
                amount: -Math.abs(Number(transaction.amount || 0))
            }));
            updateTopTransactionsChart({ transactions: chartTransactions });
        } catch (error) {
            setContainerMessage('top-transactions-container', error.message, true);
        }
    }

    async function loadDashboardData() {
        const range = getYearSelection();

        const budgetUrl = range.isYtd
            ? `/api/analytics/budget-variance?start_date=${range.startDate}&end_date=${range.endDate}`
            : `/api/analytics/budget-variance?year=${range.actualYear}`;

        const monthlyUrl = range.isYtd
            ? `/api/analytics/monthly-summary?start_date=${range.startDate}&end_date=${range.endDate}`
            : `/api/analytics/monthly-summary?year=${range.actualYear}`;

        const categoryUrl = `/api/analytics/category-breakdown?start_date=${range.startDate}&end_date=${range.endDate}`;

        const savingsUrl = range.isYtd
            ? `/api/analytics/savings-tracking?start_date=${range.startDate}&end_date=${range.endDate}`
            : `/api/analytics/savings-tracking?year=${range.actualYear}`;

        const tasks = [
            {
                url: budgetUrl,
                containerId: 'budget-variance-container',
                success: 'Budget variance data loaded. Check chart below.',
                error: 'Unable to load budget variance data.',
                render: updateBudgetVarianceChart
            },
            {
                url: monthlyUrl,
                containerId: 'monthly-overview-container',
                success: 'Monthly overview data loaded. Check chart below.',
                error: 'Unable to load monthly overview data.',
                render: updateMonthlyOverviewChart
            },
            {
                url: categoryUrl,
                containerId: 'category-breakdown-container',
                success: 'Category breakdown data loaded. Check charts below.',
                error: 'Unable to load category breakdown data.',
                render: updateCategoryBreakdownChart
            },
            {
                url: savingsUrl,
                containerId: 'savings-tracking-container',
                success: 'Savings tracking data loaded. Check chart below.',
                error: 'Unable to load savings tracking data.',
                render: updateSavingsTrackingChart
            }
        ];

        await Promise.all(
            tasks.map(async task => {
                try {
                    const data = await fetchJson(task.url, task.error);
                    setContainerMessage(task.containerId, task.success);
                    task.render(data);
                } catch (error) {
                    setContainerMessage(task.containerId, error.message, true);
                }
            })
        );

        await updateTopTransactions();
    }

    async function updateDashboardYear() {
        syncCategoryDateInputsToYear();
        await loadDashboardData();
    }

    async function updateCategoryAnalysis() {
        const startDate = document.getElementById('start-date')?.value;
        const endDate = document.getElementById('end-date')?.value;
        const categoryType = document.getElementById('category-type')?.value;

        const url = new URL('/api/analytics/category-breakdown', window.location.origin);
        if (startDate) url.searchParams.set('start_date', startDate);
        if (endDate) url.searchParams.set('end_date', endDate);
        if (categoryType) url.searchParams.set('category_type', categoryType);

        try {
            const data = await fetchJson(url.toString(), 'Loading category analysis failed');
            setContainerMessage('category-breakdown-container', 'Category analysis updated. Check charts below.');
            updateCategoryBreakdownChart(data);
        } catch (error) {
            setContainerMessage('category-breakdown-container', error.message, true);
        }
    }

    function updateQuickMonthButtonState(activeMonth) {
        document.querySelectorAll('.quick-month-btn').forEach(button => {
            const buttonMonth = Number(button.dataset.month);
            if (buttonMonth === activeMonth) {
                button.classList.remove('btn-secondary');
                button.classList.add('btn-primary');
            } else {
                button.classList.remove('btn-primary');
                button.classList.add('btn-secondary');
            }
        });
    }

    function initializeQuickMonthSelection() {
        document.querySelectorAll('.quick-month-btn').forEach(button => {
            button.addEventListener('click', () => {
                const month = Number(button.dataset.month);
                if (!month) return;

                const range = getYearSelection();
                const startDate = `${range.actualYear}-${pad2(month)}-01`;
                const endDate = monthEndLocalISO(range.actualYear, month);

                const startInput = document.getElementById('start-date');
                const endInput = document.getElementById('end-date');
                if (startInput) startInput.value = startDate;
                if (endInput) endInput.value = endDate;

                updateQuickMonthButtonState(month);
                updateCategoryAnalysis();
            });
        });

        const currentMonth = new Date().getMonth() + 1;
        updateQuickMonthButtonState(currentMonth);
    }

    function getSelectedYoyYears() {
        const selectedYears = [];
        document.querySelectorAll('#yoy-years-container input[type="checkbox"]:checked').forEach(checkbox => {
            selectedYears.push(checkbox.value);
        });
        return selectedYears;
    }

    function renderYoyYearCheckboxes(years) {
        const container = document.getElementById('yoy-years-container');
        if (!container) return;

        container.replaceChildren();

        years.forEach(year => {
            const row = document.createElement('div');
            row.className = 'flex items-center';

            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.id = `yoy-year-${year}`;
            checkbox.value = String(year);
            checkbox.className = 'mr-2';
            checkbox.checked = years.length <= 3;

            const label = document.createElement('label');
            label.htmlFor = checkbox.id;
            label.className = 'text-sm text-primary';
            label.textContent = String(year);

            row.append(checkbox, label);
            container.appendChild(row);
        });
    }

    async function populateCategorySelector() {
        const selector = document.getElementById('cumulative-category-selector');
        if (!selector) return;

        selector.replaceChildren();

        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = 'Select a category...';
        selector.appendChild(placeholder);

        try {
            const data = await fetchJson('/api/analytics/categories', 'Loading categories failed');
            const categories = Array.isArray(data.categories) ? data.categories : [];
            categories
                .slice()
                .sort((a, b) => String(a.name || '').localeCompare(String(b.name || '')))
                .forEach(category => {
                    const option = document.createElement('option');
                    option.value = String(category.id);
                    option.textContent = `${category.name} (${category.type})`;
                    selector.appendChild(option);
                });
        } catch (error) {
            console.error(error.message);
        }
    }

    async function initializeYearOverYearComparison() {
        try {
            const data = await fetchJson('/api/analytics/year-over-year', 'Loading year-over-year baseline failed');
            const years = data.summary?.years || [];
            renderYoyYearCheckboxes(years);
            await populateCategorySelector();

            if (years.length > 0) {
                await updateYearOverYearComparison();
            } else {
                setContainerMessage('yoy-comparison-container', 'No year-over-year data available yet.');
            }
        } catch (error) {
            setContainerMessage('yoy-comparison-container', error.message, true);
        }
    }

    function sortYoyTableData(columnName, data, viewMode) {
        const categories = Array.isArray(data.categories) ? [...data.categories] : [];
        const years = data.summary?.years || [];
        const lastYear = years[years.length - 1];
        const prevYear = years[years.length - 2];
        const changeKey = `${prevYear}_to_${lastYear}`;

        categories.sort((a, b) => {
            let aValue = 0;
            let bValue = 0;

            if (columnName === 'category') {
                aValue = String(a.name || '').toLowerCase();
                bValue = String(b.name || '').toLowerCase();
            } else if (years.includes(Number(columnName))) {
                const year = Number(columnName);
                aValue = viewMode === 'monthly_avg'
                    ? (a.yearly_data?.[year]?.monthly_avg || 0)
                    : (a.yearly_data?.[year]?.total || 0);
                bValue = viewMode === 'monthly_avg'
                    ? (b.yearly_data?.[year]?.monthly_avg || 0)
                    : (b.yearly_data?.[year]?.total || 0);
            } else if (columnName === 'change') {
                const aChange = a.changes?.[changeKey];
                const bChange = b.changes?.[changeKey];
                aValue = aChange ? (viewMode === 'monthly_avg' ? aChange.absolute_monthly : aChange.absolute_total) : 0;
                bValue = bChange ? (viewMode === 'monthly_avg' ? bChange.absolute_monthly : bChange.absolute_total) : 0;
            } else if (columnName === 'percent_change') {
                const aChange = a.changes?.[changeKey];
                const bChange = b.changes?.[changeKey];
                aValue = aChange ? (viewMode === 'monthly_avg' ? aChange.percentage_monthly : aChange.percentage_total) : 0;
                bValue = bChange ? (viewMode === 'monthly_avg' ? bChange.percentage_monthly : bChange.percentage_total) : 0;
            }

            if (typeof aValue === 'string') {
                return sortState.order === 'asc'
                    ? aValue.localeCompare(bValue)
                    : bValue.localeCompare(aValue);
            }

            return sortState.order === 'asc'
                ? Number(aValue) - Number(bValue)
                : Number(bValue) - Number(aValue);
        });

        return { ...data, categories };
    }

    function handleYoyHeaderClick(columnName) {
        if (!sortState.currentData || !sortState.currentViewMode) return;

        if (sortState.column === columnName) {
            sortState.order = sortState.order === 'asc' ? 'desc' : 'asc';
        } else {
            sortState.column = columnName;
            sortState.order = 'asc';
        }

        const sortedData = sortYoyTableData(columnName, sortState.currentData, sortState.currentViewMode);
        updateYearOverYearDisplay(sortedData, sortState.currentViewMode);
    }

    function updateYearOverYearDisplay(data, viewMode) {
        sortState.currentData = data;
        sortState.currentViewMode = viewMode;

        const container = document.getElementById('yoy-comparison-container');
        if (!container) return;

        const categories = Array.isArray(data.categories) ? data.categories : [];
        const years = data.summary?.years || [];

        if (categories.length === 0) {
            setContainerMessage('yoy-comparison-container', 'No data available for the selected criteria.');
            return;
        }

        const escape = window.escapeHtml;
        const arrow = column => (sortState.column === column ? (sortState.order === 'asc' ? '▲' : '▼') : '');

        let html = `
            <div class="table-container">
            <div class="overflow-x-auto">
                <table class="min-w-full">
                    <thead>
                        <tr>
                            <th class="cursor-pointer select-none" data-sort-column="category">
                                Category ${arrow('category')}
                            </th>
        `;

        years.forEach(year => {
            const yearStr = String(year);
            html += `
                <th class="cursor-pointer select-none" data-sort-column="${yearStr}">
                    ${yearStr} ${viewMode === 'monthly_avg' ? '(Avg/Mo)' : '(Total)'} ${arrow(yearStr)}
                </th>
            `;
        });

        if (years.length > 1) {
            html += `
                <th class="cursor-pointer select-none" data-sort-column="change">
                    Change ${arrow('change')}
                </th>
                <th class="cursor-pointer select-none" data-sort-column="percent_change">
                    % Change ${arrow('percent_change')}
                </th>
            `;
        }

        html += `
                        </tr>
                    </thead>
                    <tbody>
        `;

        categories.forEach(category => {
            html += '<tr>';
            html += `<td class="font-medium">${escape(category.name || '')}</td>`;

            years.forEach(year => {
                const yearData = category.yearly_data?.[year] || {};
                const value = viewMode === 'monthly_avg' ? yearData.monthly_avg : yearData.total;
                const amount = Math.abs(Number(value || 0));
                html += `<td class="text-right">${formatCurrency(amount)}</td>`;
            });

            if (years.length > 1) {
                const lastYear = years[years.length - 1];
                const prevYear = years[years.length - 2];
                const change = category.changes?.[`${prevYear}_to_${lastYear}`];

                if (change) {
                    const absoluteChange = viewMode === 'monthly_avg' ? change.absolute_monthly : change.absolute_total;
                    const percentageChange = viewMode === 'monthly_avg' ? change.percentage_monthly : change.percentage_total;
                    const shouldShowUpArrow = category.type === 'spending' ? absoluteChange < 0 : absoluteChange > 0;
                    html += `
                        <td class="text-right">
                            ${shouldShowUpArrow ? '↑' : '↓'} ${formatCurrency(Math.abs(absoluteChange || 0))}
                        </td>
                        <td class="text-right">
                            ${Number(percentageChange) > 0 ? '+' : ''}${Number(percentageChange || 0).toFixed(1)}%
                        </td>
                    `;
                } else {
                    html += '<td colspan="2" class="text-center">N/A</td>';
                }
            }

            html += '</tr>';
        });

        html += `
                    </tbody>
                </table>
            </div>
            </div>
        `;

        container.innerHTML = html;

        container.querySelectorAll('[data-sort-column]').forEach(header => {
            header.addEventListener('click', () => {
                handleYoyHeaderClick(header.dataset.sortColumn || 'category');
            });
        });
    }

    async function updateYearOverYearComparison() {
        const categoryType = document.getElementById('yoy-category-type')?.value;
        const viewMode = document.getElementById('yoy-view-mode')?.value || 'total';
        const selectedYears = getSelectedYoyYears();

        if (selectedYears.length === 0) {
            setContainerMessage('yoy-comparison-container', 'Please select at least one year to compare.');
            return;
        }

        const url = new URL('/api/analytics/year-over-year', window.location.origin);
        if (categoryType) url.searchParams.set('category_type', categoryType);
        url.searchParams.set('years', selectedYears.join(','));

        try {
            const data = await fetchJson(url.toString(), 'Loading year-over-year comparison failed');
            updateYearOverYearDisplay(data, viewMode);
            if (typeof updateYearOverYearCharts === 'function') {
                updateYearOverYearCharts(data, viewMode);
            }
        } catch (error) {
            setContainerMessage('yoy-comparison-container', error.message, true);
        }
    }

    async function updateCategoryCumulativeChart() {
        const selector = document.getElementById('cumulative-category-selector');
        const chart = document.getElementById('yoy-cumulative-chart');
        const categoryId = selector ? selector.value : '';

        if (!chart) return;

        if (!categoryId) {
            chart.style.display = 'none';
            return;
        }

        const selectedYears = getSelectedYoyYears();
        if (selectedYears.length === 0) {
            chart.style.display = 'none';
            return;
        }

        const url = new URL('/api/analytics/category-cumulative', window.location.origin);
        url.searchParams.set('category_id', categoryId);
        url.searchParams.set('years', selectedYears.join(','));

        try {
            const data = await fetchJson(url.toString(), 'Loading cumulative category data failed');
            if (data && data.category_name && typeof updateCategoryCumulativeChartDisplay === 'function') {
                updateCategoryCumulativeChartDisplay(data);
            }
        } catch (error) {
            console.error(error.message);
            chart.style.display = 'none';
        }
    }

    function generateYearOverYearCSV(data, viewMode) {
        const categories = Array.isArray(data.categories) ? data.categories : [];
        const years = data.summary?.years || [];

        let csv = 'Category,Type';

        years.forEach(year => {
            csv += `,${year} ${viewMode === 'monthly_avg' ? 'Monthly Avg' : 'Total'}`;
        });

        if (years.length > 1) {
            csv += ',Change,% Change';
        }

        csv += '\n';

        categories.forEach(category => {
            const escapedName = String(category.name || '').replace(/"/g, '""');
            csv += `"${escapedName}",${category.type || ''}`;

            years.forEach(year => {
                const yearData = category.yearly_data?.[year] || {};
                const value = viewMode === 'monthly_avg' ? yearData.monthly_avg : yearData.total;
                csv += `,${Number(value || 0)}`;
            });

            if (years.length > 1) {
                const lastYear = years[years.length - 1];
                const prevYear = years[years.length - 2];
                const change = category.changes?.[`${prevYear}_to_${lastYear}`];
                if (change) {
                    const absoluteChange = viewMode === 'monthly_avg' ? change.absolute_monthly : change.absolute_total;
                    const percentageChange = viewMode === 'monthly_avg' ? change.percentage_monthly : change.percentage_total;
                    csv += `,${Number(absoluteChange || 0)},${Number(percentageChange || 0)}`;
                } else {
                    csv += ',,';
                }
            }

            csv += '\n';
        });

        return csv;
    }

    function downloadCSV(csv, filename) {
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(link.href);
    }

    async function exportYearOverYearData() {
        const categoryType = document.getElementById('yoy-category-type')?.value;
        const viewMode = document.getElementById('yoy-view-mode')?.value || 'total';
        const selectedYears = getSelectedYoyYears();

        if (selectedYears.length === 0) {
            alert('Please select at least one year to export.');
            return;
        }

        const url = new URL('/api/analytics/year-over-year', window.location.origin);
        if (categoryType) url.searchParams.set('category_type', categoryType);
        url.searchParams.set('years', selectedYears.join(','));

        try {
            const data = await fetchJson(url.toString(), 'Export failed');
            const csv = generateYearOverYearCSV(data, viewMode);
            downloadCSV(csv, `year-over-year-comparison-${todayLocalISO()}.csv`);
        } catch (error) {
            alert(error.message);
        }
    }

    function bindEvents() {
        document.getElementById('global-year-selector')?.addEventListener('change', () => {
            updateDashboardYear();
        });

        document.getElementById('month-selector')?.addEventListener('change', () => {
            updateTopTransactions();
        });

        document.getElementById('top-transactions-update-btn')?.addEventListener('click', () => {
            updateTopTransactions();
        });

        document.getElementById('category-analysis-update-btn')?.addEventListener('click', () => {
            updateCategoryAnalysis();
        });

        document.getElementById('yoy-update-btn')?.addEventListener('click', () => {
            updateYearOverYearComparison();
        });

        document.getElementById('yoy-export-btn')?.addEventListener('click', () => {
            exportYearOverYearData();
        });

        document.getElementById('cumulative-category-selector')?.addEventListener('change', () => {
            updateCategoryCumulativeChart();
        });
    }

    async function initializePage() {
        if (!document.getElementById('global-year-selector')) return;

        if (typeof loadThemeColors === 'function') {
            loadThemeColors();
        }
        if (typeof initChartTheme === 'function') {
            initChartTheme();
        }

        bindEvents();
        initializeQuickMonthSelection();

        await populateYearSelector();

        const monthSelector = document.getElementById('month-selector');
        if (monthSelector) {
            monthSelector.value = String(new Date().getMonth() + 1);
        }

        syncCategoryDateInputsToYear();
        await loadDashboardData();
        await initializeYearOverYearComparison();
    }

    // Expose for compatibility with existing chart integration.
    window.updateCategoryCumulativeChart = updateCategoryCumulativeChart;

    document.addEventListener('DOMContentLoaded', () => {
        initializePage().catch(error => {
            console.error('Failed to initialize analytics page:', error);
        });
    });
})();
