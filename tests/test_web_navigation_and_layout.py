"""Tests for web navigation wiring, layout privacy defaults, and analytics page script setup."""


def test_root_home_page_contains_workflow(test_client):
    """Root route should render the new workflow home page."""
    response = test_client.get("/")

    assert response.status_code == 200
    html = response.text
    assert "workflow-card" in html
    assert 'href="/import"' in html
    assert 'href="/review"' in html
    assert 'href="/analytics"' in html
    assert 'href="/export"' in html


def test_app_route_redirects_to_root(test_client):
    """Legacy /app route should redirect to the new root home page."""
    response = test_client.get("/app", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/"


def test_layout_uses_no_js_class_and_no_google_fonts(test_client):
    """Base layout should default to no-JS mode and avoid external Google Fonts."""
    response = test_client.get("/import")

    assert response.status_code == 200
    html = response.text
    assert '<html lang="en" class="no-js">' in html
    assert "fonts.googleapis.com" not in html
    assert "fonts.gstatic.com" not in html


def test_analytics_page_uses_controller_script_without_inline_handlers(test_client):
    """Analytics page should use the dedicated controller script instead of large inline handlers."""
    response = test_client.get("/analytics")

    assert response.status_code == 200
    html = response.text
    assert "/static/js/analytics_page.js" in html
    assert "function populateYearSelector" not in html
    assert "onclick=" not in html
    assert "onchange=" not in html
