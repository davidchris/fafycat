#!/usr/bin/env python3
"""Quick performance test to identify bottlenecks."""

import time
import requests
import sys
import pytest

pytestmark = [pytest.mark.requires_server, pytest.mark.perf]


def test_page_performance():
    """Test loading times of main pages."""
    base_url = "http://localhost:8000"
    pages = ["/app", "/import", "/review", "/settings"]

    print("🔬 FafyCat Performance Test")
    print("=" * 50)

    # Verify server is running
    _verify_server_running(base_url)

    # Test page performance
    _test_pages_performance(base_url, pages)

    # Test ML API performance
    _test_ml_api_performance(base_url)

    # Print completion message
    _print_completion_tips()


def _verify_server_running(base_url: str) -> None:
    """Verify that the server is running and responsive."""
    try:
        response = requests.get(f"{base_url}/app", timeout=10)
        if response.status_code != 200:
            print(f"❌ Server not responding properly (status: {response.status_code})")
            pytest.skip("Server not responding properly")
    except requests.exceptions.RequestException:
        print(f"❌ Cannot connect to server at {base_url}")
        print("   Make sure to run: uv run fafycat serve --dev")
        pytest.skip("Cannot connect to server")

    print("✅ Server is running\n")


def _test_pages_performance(base_url: str, pages: list[str]) -> None:
    """Test the performance of main application pages."""
    for page in pages:
        print(f"Testing {page}...")
        _test_single_page(base_url, page)
        time.sleep(0.1)  # Small delay between requests


def _test_single_page(base_url: str, page: str) -> None:
    """Test the performance of a single page."""
    start = time.time()
    try:
        response = requests.get(f"{base_url}{page}", timeout=10)
        duration = time.time() - start
        _report_page_result(page, response.status_code, duration)
    except requests.exceptions.Timeout:
        print(f"  ❌ ⏰ {page}: TIMEOUT (>10s)")
    except requests.exceptions.RequestException as e:
        print(f"  ❌ 💥 {page}: ERROR - {e}")


def _report_page_result(page: str, status_code: int, duration: float) -> None:
    """Report the results for a single page test."""
    status_emoji = "✅" if status_code == 200 else "❌"
    speed_emoji = "🐌" if duration > 1.0 else "⚡" if duration < 0.1 else "🏃"

    print(f"  {status_emoji} {speed_emoji} {page}: {duration:.3f}s (status: {status_code})")

    if duration > 1.0:
        print(f"    ⚠️  VERY SLOW: {page} took {duration:.1f}s")
    elif duration > 0.5:
        print(f"    ⚠️  SLOW: {page} took {duration:.1f}s")


def _test_ml_api_performance(base_url: str) -> None:
    """Test the ML API performance specifically."""
    print("\n" + "=" * 50)
    print("🧪 Testing ML Status API directly...")

    start = time.time()
    try:
        response = requests.get(f"{base_url}/api/ml/status", timeout=10)
        duration = time.time() - start
        _report_ml_api_result(response, duration)
    except requests.exceptions.RequestException as e:
        print(f"  ❌ ML Status API error: {e}")


def _report_ml_api_result(response, duration: float) -> None:
    """Report the ML API test results."""
    status_emoji = "✅" if response.status_code == 200 else "❌"
    speed_emoji = "🐌" if duration > 0.5 else "⚡" if duration < 0.1 else "🏃"

    print(f"  {status_emoji} {speed_emoji} /api/ml/status: {duration:.3f}s")

    if response.status_code == 200:
        data = response.json()
        print(f"    Model loaded: {data.get('model_loaded', False)}")
        print(f"    Training ready: {data.get('training_ready', False)}")
        print(f"    Reviewed transactions: {data.get('reviewed_transactions', 0)}")

    if duration > 0.5:
        print(f"    ⚠️  ML Status API is slow: {duration:.1f}s")
        print("    💡 This might be causing page slowness!")


def _print_completion_tips() -> None:
    """Print completion message and performance tips."""
    print("\n🏁 Performance test complete!")
    print("\n💡 Tips:")
    print("  - Pages should load in <100ms")
    print("  - API calls should take <50ms")
    print("  - Check server console for detailed timing logs")


if __name__ == "__main__":
    test_page_performance()
