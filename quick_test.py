#!/usr/bin/env python3
"""Quick test to isolate the issue."""

import time

import requests


def quick_test():
    """Test just one page to see timing."""
    print("🔬 Quick Performance Test")
    print("=" * 30)

    url = "http://localhost:8001/import"

    print(f"Testing {url}...")
    start = time.time()
    try:
        response = requests.get(url, timeout=10)
        duration = time.time() - start

        print(f"Status: {response.status_code}")
        print(f"Duration: {duration:.3f}s")
        print(f"Content-Length: {len(response.text)} chars")

        # Check headers for our performance middleware
        process_time = response.headers.get("X-Process-Time")
        if process_time:
            print(f"Server Process Time: {process_time}s")
        else:
            print("❌ No X-Process-Time header (middleware not active?)")

    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    quick_test()
