"""Streamlit app entry point for FafyCat."""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from fafycat.app import main

if __name__ == "__main__":
    main()
