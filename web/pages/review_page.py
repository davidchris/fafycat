"""Review and categorize transactions page."""

from fastapi import Request
from web.components.layout import create_page_layout


def render_review_page(request: Request):
    """Render the review and categorize transactions page."""
    content = '''
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-2xl font-bold mb-6">Review & Categorize</h1>
        
        <div class="mb-8">
            <h2 class="text-lg font-semibold mb-4">Pending Review</h2>
            <p class="text-gray-600 mb-4">Transactions requiring manual review will appear here.</p>
            <div class="bg-white rounded-lg shadow p-6">
                <p class="text-center text-gray-500 py-8">No transactions to review at the moment.</p>
            </div>
        </div>
        
        <div class="mb-8">
            <h2 class="text-lg font-semibold mb-4">Filters</h2>
            <div class="bg-gray-50 p-4 rounded">
                <label class="block text-sm font-medium mb-2">Confidence threshold:</label>
                <input type="range" min="0" max="1" step="0.1" value="0.5" class="w-full">
                <p class="text-sm text-gray-600 mt-2">Show transactions with confidence below 50%</p>
            </div>
        </div>
    </div>
    '''
    
    return create_page_layout("Review & Categorize - FafyCat", content)