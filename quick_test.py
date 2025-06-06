#!/usr/bin/env python3
"""Quick test to isolate the issue."""

import time

import requests


def quick_test():
    """Test just one page to see timing."""

    url = "http://localhost:8001/import"

    start = time.time()
    try:
        response = requests.get(url, timeout=10)
        time.time() - start


        # Check headers for our performance middleware
        process_time = response.headers.get("X-Process-Time")
        if process_time:
            pass
        else:
            pass

    except Exception:
        pass


if __name__ == "__main__":
    quick_test()
