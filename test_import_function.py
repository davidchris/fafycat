#!/usr/bin/env python3
"""Test the import page function directly to see the error."""

import os
import sys
from pathlib import Path

# Add project root to Python path for imports
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Set environment for development
os.environ["FAFYCAT_DB_URL"] = "sqlite:///data/fafycat_dev.db"
os.environ["FAFYCAT_ENV"] = "development"


def test_import_function():
    """Test the import page function."""
    try:
        from web.pages.import_page import _get_ml_status_sync

        print("Testing _get_ml_status_sync()...")

        result = _get_ml_status_sync()
        print(f"✅ Success: {result}")

    except Exception as e:
        print(f"❌ Error in _get_ml_status_sync(): {e}")
        import traceback

        traceback.print_exc()

    try:
        from web.pages.import_page import _get_import_model_status_alert

        print("\nTesting _get_import_model_status_alert()...")

        result = _get_import_model_status_alert()
        print(f"✅ Success: HTML length = {len(result)} chars")

    except Exception as e:
        print(f"❌ Error in _get_import_model_status_alert(): {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_import_function()
