"""Export configuration page."""

import html as html_mod
from datetime import date, timedelta

from fastapi import Request
from sqlalchemy.orm import Session

from src.fafycat.core.database import get_categories
from web.components.layout import create_page_layout


def create_export_page(request: Request, db_session: Session):
    """Create the export configuration page."""

    # Get available categories for filtering
    categories = get_categories(db_session)

    # Generate some default date options
    today = date.today()
    last_month = today - timedelta(days=30)
    last_three_months = today - timedelta(days=90)
    last_year = today - timedelta(days=365)

    content = f"""
    <div class="p-8">
        <div class="max-w-4xl mx-auto">
            <div class="mb-8">
                <h1 class="text-3xl font-bold mb-4">Export Data</h1>
                <p class="text-secondary">Export your transaction data for analysis in various formats</p>
            </div>

            <!-- Export Summary Card -->
            <div class="card mb-8" id="export-summary">
                <h2 class="card-header">Export Preview</h2>
                <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                    <div class="stat-card stat-saving">
                        <div class="stat-value" id="total-transactions">-</div>
                        <div class="stat-label">Total Transactions</div>
                    </div>
                    <div class="stat-card stat-success">
                        <div class="stat-value" id="reviewed-transactions">-</div>
                        <div class="stat-label">Reviewed</div>
                    </div>
                    <div class="stat-card stat-income">
                        <div class="stat-value" id="total-amount">-</div>
                        <div class="stat-label">Total Amount</div>
                    </div>
                </div>
                <div class="text-sm text-tertiary" id="date-range">Select filters to see export preview</div>
            </div>

            <!-- Export Configuration Form -->
            <div class="card">
                <h2 class="card-header">Export Configuration</h2>

                <form id="export-form" class="space-y-6">
                    <!-- Format Selection -->
                    <div>
                        <label class="form-label mb-3">Export Format</label>
                        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                            <label class="format-option">
                                <input type="radio" name="format" value="csv" class="mr-3" checked>
                                <div>
                                    <div class="font-medium">CSV</div>
                                    <div class="text-sm text-secondary">Spreadsheet-ready format</div>
                                </div>
                            </label>
                            <label class="format-option">
                                <input type="radio" name="format" value="excel" class="mr-3">
                                <div>
                                    <div class="font-medium">Excel</div>
                                    <div class="text-sm text-secondary">Multi-sheet workbook</div>
                                </div>
                            </label>
                            <label class="format-option">
                                <input type="radio" name="format" value="json" class="mr-3">
                                <div>
                                    <div class="font-medium">JSON</div>
                                    <div class="text-sm text-secondary">Programmatic access</div>
                                </div>
                            </label>
                        </div>
                    </div>

                    <!-- Date Range -->
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label class="form-label mb-2">Start Date</label>
                            <input type="date" name="start_date" id="start_date"
                                   class="form-input"
                                   hx-trigger="change" hx-post="/api/export/summary" hx-target="#export-summary" hx-include="#export-form">
                        </div>
                        <div>
                            <label class="form-label mb-2">End Date</label>
                            <input type="date" name="end_date" id="end_date"
                                   class="form-input"
                                   hx-trigger="change" hx-post="/api/export/summary" hx-target="#export-summary" hx-include="#export-form">
                        </div>
                    </div>

                    <!-- Quick Date Presets -->
                    <div>
                        <label class="form-label mb-3">Quick Date Ranges</label>
                        <div class="flex flex-wrap gap-2">
                            <button type="button" class="btn btn-secondary date-preset"
                                    data-start="" data-end="">All Time</button>
                            <button type="button" class="btn btn-secondary date-preset"
                                    data-start="{last_month.isoformat()}" data-end="{
        today.isoformat()
    }">Last 30 Days</button>
                            <button type="button" class="btn btn-secondary date-preset"
                                    data-start="{last_three_months.isoformat()}" data-end="{
        today.isoformat()
    }">Last 3 Months</button>
                            <button type="button" class="btn btn-secondary date-preset"
                                    data-start="{last_year.isoformat()}" data-end="{
        today.isoformat()
    }">Last Year</button>
                        </div>
                    </div>

                    <!-- Category Filter -->
                    <div>
                        <label class="form-label mb-3">Filter by Categories (optional)</label>
                        <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3 max-h-48 overflow-y-auto p-4" style="border: 1px solid var(--border-default); border-radius: 4px;">
                            {
        "".join(
            [
                f'''<label class="flex items-center space-x-2 text-sm">
                                    <input type="checkbox" name="categories" value="{html_mod.escape(str(cat.name))}" class="rounded"
                                           hx-trigger="change" hx-post="/api/export/summary" hx-target="#export-summary" hx-include="#export-form">
                                    <span class="truncate" title="{html_mod.escape(str(cat.name))}">{html_mod.escape(str(cat.name))}</span>
                                    <span class="text-xs text-tertiary">({html_mod.escape(str(cat.type))})</span>
                                </label>'''
                for cat in categories
            ]
        )
    }
                        </div>
                    </div>

                    <!-- Export Actions -->
                    <div class="flex items-center justify-between pt-6" style="border-top: 1px solid var(--border-subtle);">
                        <button type="button"
                                class="btn btn-ghost"
                                hx-post="/api/export/summary" hx-target="#export-summary" hx-include="#export-form">
                            Update Preview
                        </button>
                        <div class="space-x-3">
                            <button type="button" id="export-btn"
                                    class="btn btn-primary"
                                    onclick="exportData()">
                                Export Data
                            </button>
                        </div>
                    </div>
                </form>
            </div>

            <!-- Export History -->
            <div class="card mt-8">
                <h2 class="card-header">Export Tips</h2>
                <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <div class="text-center">
                        <h3 class="font-medium mb-2">CSV Format</h3>
                        <p class="text-sm text-secondary">Best for spreadsheet applications like Excel or Google Sheets. Simple, universal format.</p>
                    </div>
                    <div class="text-center">
                        <h3 class="font-medium mb-2">Excel Format</h3>
                        <p class="text-sm text-secondary">Includes multiple sheets with transaction data, category summaries, and monthly reports.</p>
                    </div>
                    <div class="text-center">
                        <h3 class="font-medium mb-2">JSON Format</h3>
                        <p class="text-sm text-secondary">Perfect for developers and programmatic analysis. Includes all metadata and structure.</p>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Format selection styling
        document.querySelectorAll('input[name="format"]').forEach(radio => {{
            radio.addEventListener('change', function() {{
                document.querySelectorAll('.format-option').forEach(option => {{
                    option.classList.remove('selected');
                }});
                if (this.checked) {{
                    this.closest('.format-option').classList.add('selected');
                }}
            }});
        }});

        // Date preset buttons
        document.querySelectorAll('.date-preset').forEach(button => {{
            button.addEventListener('click', function() {{
                const startDate = this.dataset.start;
                const endDate = this.dataset.end;

                document.getElementById('start_date').value = startDate;
                document.getElementById('end_date').value = endDate;

                // Trigger HTMX update
                htmx.trigger('#start_date', 'change');
            }});
        }});

        // Export function
        async function exportData() {{
            const form = document.getElementById('export-form');
            const formData = new FormData(form);

            // Build export request
            const exportRequest = {{
                format: formData.get('format'),
                start_date: formData.get('start_date') || null,
                end_date: formData.get('end_date') || null,
                categories: formData.getAll('categories')
            }};

            try {{
                // Disable export button
                const exportBtn = document.getElementById('export-btn');
                exportBtn.disabled = true;
                exportBtn.textContent = 'Exporting...';

                // Make API request
                const response = await fetch('/api/export/transactions', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                    }},
                    body: JSON.stringify(exportRequest)
                }});

                if (response.ok) {{
                    // Get filename from response headers
                    const contentDisposition = response.headers.get('Content-Disposition');
                    let filename = 'fafycat_export';
                    if (contentDisposition) {{
                        const match = contentDisposition.match(/filename=(.+)/);
                        if (match) {{
                            filename = match[1].replace(/"/g, '');
                        }}
                    }}

                    // Download the file
                    const blob = await response.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    window.URL.revokeObjectURL(url);
                    document.body.removeChild(a);
                }} else {{
                    const errorText = await response.text();
                    alert('Export failed: ' + errorText);
                }}
            }} catch (error) {{
                alert('Export failed: ' + error.message);
            }} finally {{
                // Re-enable export button
                const exportBtn = document.getElementById('export-btn');
                exportBtn.disabled = false;
                exportBtn.textContent = 'Export Data';
            }}
        }}

        // Initialize format selection
        document.querySelector('input[name="format"]:checked').dispatchEvent(new Event('change'));

        // Load initial summary
        htmx.trigger('#start_date', 'change');
    </script>
    """

    return create_page_layout("Export Data - FafyCat", content)


def create_export_summary_response(summary_data: dict):
    """Create HTMX response for export summary update."""
    total_transactions = summary_data.get("total_transactions", 0)
    reviewed_transactions = summary_data.get("reviewed_transactions", 0)
    amount_stats = summary_data.get("amount_statistics", {})
    date_range = summary_data.get("date_range", {})
    filters = summary_data.get("filters_applied", {})

    # Format amount
    total_amount = amount_stats.get("total", 0)
    amount_str = f"€{total_amount:,.2f}" if total_amount else "€0.00"

    # Format date range
    date_range_str = "No data available"
    if date_range:
        start = date_range.get("earliest", "")
        end = date_range.get("latest", "")
        if start and end:
            date_range_str = f"Data from {start} to {end}"

    # Add filter info
    filter_info = []
    if filters.get("start_date"):
        filter_info.append(f"from {filters['start_date']}")
    if filters.get("end_date"):
        filter_info.append(f"until {filters['end_date']}")
    if filters.get("categories"):
        cat_count = len(filters["categories"])
        filter_info.append(f"{cat_count} categories selected")

    if filter_info:
        date_range_str += f" • Filters: {', '.join(filter_info)}"

    return f"""
    <h2 class="card-header">Export Preview</h2>
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
        <div class="stat-card stat-saving">
            <div class="stat-value">{total_transactions:,}</div>
            <div class="stat-label">Total Transactions</div>
        </div>
        <div class="stat-card stat-success">
            <div class="stat-value">{reviewed_transactions:,}</div>
            <div class="stat-label">Reviewed</div>
        </div>
        <div class="stat-card stat-income">
            <div class="stat-value">{amount_str}</div>
            <div class="stat-label">Total Amount</div>
        </div>
    </div>
    <div class="text-sm text-tertiary">{date_range_str}</div>
    """
