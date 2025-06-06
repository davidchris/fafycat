#!/usr/bin/env python3
"""Quick performance test to identify bottlenecks."""

import time
import requests
import sys


def test_page_performance():
    """Test loading times of main pages."""
    base_url = "http://localhost:8000"
    pages = ["/app", "/import", "/review", "/settings"]

    print("🔬 FafyCat Performance Test")
    print("=" * 50)

    # Test if server is running
    try:
        response = requests.get(f"{base_url}/app", timeout=10)
        if response.status_code != 200:
            print(f"❌ Server not responding properly (status: {response.status_code})")
            sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"❌ Cannot connect to server at {base_url}")
        print("   Make sure to run: uv run python run_dev.py")
        sys.exit(1)

    print("✅ Server is running\n")

    for page in pages:
        print(f"Testing {page}...")

        # Test page load time
        start = time.time()
        try:
            response = requests.get(f"{base_url}{page}", timeout=10)
            duration = time.time() - start

            status_emoji = "✅" if response.status_code == 200 else "❌"
            speed_emoji = "🐌" if duration > 1.0 else "⚡" if duration < 0.1 else "🏃"

            print(f"  {status_emoji} {speed_emoji} {page}: {duration:.3f}s (status: {response.status_code})")

            if duration > 1.0:
                print(f"    ⚠️  VERY SLOW: {page} took {duration:.1f}s")
            elif duration > 0.5:
                print(f"    ⚠️  SLOW: {page} took {duration:.1f}s")

        except requests.exceptions.Timeout:
            print(f"  ❌ ⏰ {page}: TIMEOUT (>10s)")
        except requests.exceptions.RequestException as e:
            print(f"  ❌ 💥 {page}: ERROR - {e}")

        # Small delay between requests
        time.sleep(0.1)

    print("\n" + "=" * 50)
    print("🧪 Testing ML Status API directly...")

    # Test ML status API specifically
    start = time.time()
    try:
        response = requests.get(f"{base_url}/api/ml/status", timeout=10)
        duration = time.time() - start

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

    except requests.exceptions.RequestException as e:
        print(f"  ❌ ML Status API error: {e}")

    print("\n🏁 Performance test complete!")
    print("\n💡 Tips:")
    print("  - Pages should load in <100ms")
    print("  - API calls should take <50ms")
    print("  - Check server console for detailed timing logs")


if __name__ == "__main__":
    test_page_performance()
