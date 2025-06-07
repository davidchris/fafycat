"""Export configuration page."""

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
                <h1 class="text-3xl font-bold mb-4">📊 Export Data</h1>
                <p class="text-gray-600">Export your transaction data for analysis in various formats</p>
            </div>

            <!-- Export Summary Card -->
            <div class="bg-white rounded-lg shadow-md p-6 mb-8" id="export-summary">
                <h2 class="text-xl font-semibold mb-4">Export Preview</h2>
                <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                    <div class="bg-blue-50 p-4 rounded-lg">
                        <div class="text-2xl font-bold text-blue-600" id="total-transactions">-</div>
                        <div class="text-sm text-gray-600">Total Transactions</div>
                    </div>
                    <div class="bg-green-50 p-4 rounded-lg">
                        <div class="text-2xl font-bold text-green-600" id="reviewed-transactions">-</div>
                        <div class="text-sm text-gray-600">Reviewed</div>
                    </div>
                    <div class="bg-yellow-50 p-4 rounded-lg">
                        <div class="text-2xl font-bold text-yellow-600" id="total-amount">-</div>
                        <div class="text-sm text-gray-600">Total Amount</div>
                    </div>
                </div>
                <div class="text-sm text-gray-500" id="date-range">Select filters to see export preview</div>
            </div>

            <!-- Export Configuration Form -->
            <div class="bg-white rounded-lg shadow-md p-6">
                <h2 class="text-xl font-semibold mb-6">Export Configuration</h2>
                
                <form id="export-form" class="space-y-6">
                    <!-- Format Selection -->
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-3">Export Format</label>
                        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                            <label class="flex items-center p-4 border-2 border-gray-200 rounded-lg cursor-pointer hover:border-blue-300 format-option">
                                <input type="radio" name="format" value="csv" class="mr-3" checked>
                                <div>
                                    <div class="font-medium">CSV</div>
                                    <div class="text-sm text-gray-500">Spreadsheet-ready format</div>
                                </div>
                            </label>
                            <label class="flex items-center p-4 border-2 border-gray-200 rounded-lg cursor-pointer hover:border-blue-300 format-option">
                                <input type="radio" name="format" value="excel" class="mr-3">
                                <div>
                                    <div class="font-medium">Excel</div>
                                    <div class="text-sm text-gray-500">Multi-sheet workbook</div>
                                </div>
                            </label>
                            <label class="flex items-center p-4 border-2 border-gray-200 rounded-lg cursor-pointer hover:border-blue-300 format-option">
                                <input type="radio" name="format" value="json" class="mr-3">
                                <div>
                                    <div class="font-medium">JSON</div>
                                    <div class="text-sm text-gray-500">Programmatic access</div>
                                </div>
                            </label>
                        </div>
                    </div>

                    <!-- Date Range -->
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">Start Date</label>
                            <input type="date" name="start_date" id="start_date" 
                                   class="w-full p-3 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                                   hx-trigger="change" hx-post="/api/export/summary" hx-target="#export-summary" hx-include="#export-form">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">End Date</label>
                            <input type="date" name="end_date" id="end_date" 
                                   class="w-full p-3 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                                   hx-trigger="change" hx-post="/api/export/summary" hx-target="#export-summary" hx-include="#export-form">
                        </div>
                    </div>

                    <!-- Quick Date Presets -->
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-3">Quick Date Ranges</label>
                        <div class="flex flex-wrap gap-2">
                            <button type="button" class="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 date-preset" 
                                    data-start="" data-end="">All Time</button>
                            <button type="button" class="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 date-preset" 
                                    data-start="{last_month.isoformat()}" data-end="{
        today.isoformat()
    }">Last 30 Days</button>
                            <button type="button" class="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 date-preset" 
                                    data-start="{last_three_months.isoformat()}" data-end="{
        today.isoformat()
    }">Last 3 Months</button>
                            <button type="button" class="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 date-preset" 
                                    data-start="{last_year.isoformat()}" data-end="{
        today.isoformat()
    }">Last Year</button>
                        </div>
                    </div>

                    <!-- Category Filter -->
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-3">Filter by Categories (optional)</label>
                        <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3 max-h-48 overflow-y-auto border border-gray-200 rounded-lg p-4">
                            {
        "".join(
            [
                f'''<label class="flex items-center space-x-2 text-sm">
                                    <input type="checkbox" name="categories" value="{cat.name}" class="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                                           hx-trigger="change" hx-post="/api/export/summary" hx-target="#export-summary" hx-include="#export-form">
                                    <span class="truncate" title="{cat.name}">{cat.name}</span>
                                    <span class="text-xs text-gray-500">({cat.type})</span>
                                </label>'''
                for cat in categories
            ]
        )
    }
                        </div>
                    </div>

                    <!-- Export Actions -->
                    <div class="flex items-center justify-between pt-6 border-t border-gray-200">
                        <button type="button" 
                                class="px-4 py-2 text-gray-600 hover:text-gray-800" 
                                hx-post="/api/export/summary" hx-target="#export-summary" hx-include="#export-form">
                            🔄 Update Preview
                        </button>
                        <div class="space-x-3">
                            <button type="button" id="export-btn" 
                                    class="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
                                    onclick="exportData()">
                                📥 Export Data
                            </button>
                        </div>
                    </div>
                </form>
            </div>

            <!-- Export History -->
            <div class="bg-white rounded-lg shadow-md p-6 mt-8">
                <h2 class="text-xl font-semibold mb-4">Export Tips</h2>
                <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <div class="text-center">
                        <div class="text-3xl mb-2">📄</div>
                        <h3 class="font-medium mb-2">CSV Format</h3>
                        <p class="text-sm text-gray-600">Best for spreadsheet applications like Excel or Google Sheets. Simple, universal format.</p>
                    </div>
                    <div class="text-center">
                        <div class="text-3xl mb-2">📊</div>
                        <h3 class="font-medium mb-2">Excel Format</h3>
                        <p class="text-sm text-gray-600">Includes multiple sheets with transaction data, category summaries, and monthly reports.</p>
                    </div>
                    <div class="text-center">
                        <div class="text-3xl mb-2">🔧</div>
                        <h3 class="font-medium mb-2">JSON Format</h3>
                        <p class="text-sm text-gray-600">Perfect for developers and programmatic analysis. Includes all metadata and structure.</p>
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
                    option.classList.remove('border-blue-500', 'bg-blue-50');
                    option.classList.add('border-gray-200');
                }});
                if (this.checked) {{
                    this.closest('.format-option').classList.remove('border-gray-200');
                    this.closest('.format-option').classList.add('border-blue-500', 'bg-blue-50');
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
                exportBtn.textContent = '⏳ Exporting...';
                
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
                exportBtn.textContent = '📥 Export Data';
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
    <h2 class="text-xl font-semibold mb-4">Export Preview</h2>
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
        <div class="bg-blue-50 p-4 rounded-lg">
            <div class="text-2xl font-bold text-blue-600">{total_transactions:,}</div>
            <div class="text-sm text-gray-600">Total Transactions</div>
        </div>
        <div class="bg-green-50 p-4 rounded-lg">
            <div class="text-2xl font-bold text-green-600">{reviewed_transactions:,}</div>
            <div class="text-sm text-gray-600">Reviewed</div>
        </div>
        <div class="bg-yellow-50 p-4 rounded-lg">
            <div class="text-2xl font-bold text-yellow-600">{amount_str}</div>
            <div class="text-sm text-gray-600">Total Amount</div>
        </div>
    </div>
    <div class="text-sm text-gray-500">{date_range_str}</div>
    """
