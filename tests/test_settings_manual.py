#!/usr/bin/env python3
"""Manual test for settings page ML training functionality."""

import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.manual

# Add project root to Python path for imports
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Set development environment
os.environ["FAFYCAT_DB_URL"] = "sqlite:///data/fafycat_dev.db"
os.environ["FAFYCAT_ENV"] = "development"

from fastapi.testclient import TestClient
from fafycat.app import app


def test_settings_page_basic():
    """Test basic settings page functionality."""
    print("🧪 Testing Settings Page ML Training")
    print("=" * 50)

    client = TestClient(app)

    try:
        response = client.get("/settings")
        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            _test_successful_page_load(response.text)
        else:
            _test_failed_page_load(response)

    except Exception as e:
        print(f"❌ Test failed: {e}")


def _test_successful_page_load(html: str) -> None:
    """Test successful page load scenarios."""
    print("\n✅ Page loaded successfully!")

    _check_ml_training_section(html)
    _check_javascript_functions(html)
    _check_api_endpoints(html)
    _check_training_status(html)


def _check_ml_training_section(html: str) -> None:
    """Check if ML training section is present."""
    if "ML Model Training" in html or "ML Model Status" in html:
        print("✅ ML training section found")
    else:
        print("❌ ML training section missing")


def _check_javascript_functions(html: str) -> None:
    """Check for required JavaScript functions."""
    js_functions = ["trainModel", "retrainModel", "predictUnpredicted"]
    found_functions = []
    for func in js_functions:
        if f"function {func}(" in html:
            found_functions.append(func)

    print(f"📝 JavaScript functions found: {found_functions}")


def _check_api_endpoints(html: str) -> None:
    """Check for required API endpoints in the HTML."""
    api_endpoints = ["/api/ml/retrain", "/api/ml/predict/batch-unpredicted"]
    found_endpoints = []
    for endpoint in api_endpoints:
        if endpoint in html:
            found_endpoints.append(endpoint)

    print(f"🔗 API endpoints found: {found_endpoints}")


def _check_training_status(html: str) -> None:
    """Check the ML training status displayed on the page."""
    if "Train ML Model Now" in html:
        print("✅ Train button found (ready to train)")
    elif "Model is loaded and working" in html:
        print("✅ Model status found (model working)")
    elif "Need more training data" in html:
        print("⚠️ Need more data message found")
    else:
        print("❓ Unknown ML status")


def _test_failed_page_load(response) -> None:
    """Handle failed page load scenarios."""
    print(f"❌ Page failed to load: {response.status_code}")
    print(response.text[:500])


def test_ml_status_api():
    """Test ML status API."""
    print("\n🔍 Testing ML Status API")
    print("-" * 30)

    client = TestClient(app)

    try:
        response = client.get("/api/ml/status")
        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            status = response.json()
            print("ML Status:")
            for key, value in status.items():
                print(f"  {key}: {value}")
        else:
            print(f"❌ API failed: {response.status_code}")
            print(response.text)

    except Exception as e:
        print(f"❌ API test failed: {e}")


if __name__ == "__main__":
    test_settings_page_basic()
    test_ml_status_api()
