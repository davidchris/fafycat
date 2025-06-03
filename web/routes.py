"""Web routes for HTML pages."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from web.components.layout import create_page_layout


router = APIRouter()


@router.get("/app", response_class=HTMLResponse)
async def main_app(request: Request):
    """Main application page."""
    content = '''
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-3xl font-bold text-center mb-8">🐱 FafyCat</h1>
        <p class="text-center text-gray-600 mb-8">Family Finance Categorizer</p>
        <p class="text-center">Welcome to the FastAPI + FastHTML version!</p>
    </div>
    '''
    return create_page_layout("FafyCat - Family Finance Categorizer", content)


@router.get("/import", response_class=HTMLResponse)
async def import_page(request: Request):
    """Import transactions page."""
    from web.pages.import_page import render_import_page
    return render_import_page(request)


@router.get("/review", response_class=HTMLResponse)
async def review_page(request: Request):
    """Review and categorize transactions page."""
    from web.pages.review_page import render_review_page
    return render_review_page(request)


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Settings and categories page."""
    from web.pages.settings_page import render_settings_page
    return render_settings_page(request)