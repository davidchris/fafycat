"""Pytest configuration and shared fixtures."""

import sys
from pathlib import Path

import pytest

# Add src and project root to Python path for imports
src_path = Path(__file__).parent.parent / "src"
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(src_path))
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session")
def test_data_dir():
    """Return the test data directory."""
    return Path(__file__).parent / "fixtures"
