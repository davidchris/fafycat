#!/usr/bin/env python3
"""Run FafyCat in development mode with test data."""

import os
import subprocess
import sys
from pathlib import Path


def main():
    """Run FafyCat in development mode."""
    # Set development environment
    os.environ["FAFYCAT_DB_URL"] = "sqlite:///data/fafycat_dev.db"
    os.environ["FAFYCAT_ENV"] = "development"

    app_dir = Path(__file__).parent
    streamlit_app = app_dir / "streamlit_app.py"

    print("🐱 Starting FafyCat in DEVELOPMENT mode")
    print(f"📊 Database: {os.environ['FAFYCAT_DB_URL']}")
    print("🧪 Using synthetic test data")
    print("-" * 50)

    try:
        subprocess.run([
            sys.executable, "-m", "streamlit", "run", str(streamlit_app),
            "--server.port", "8501"
        ], cwd=app_dir)
    except KeyboardInterrupt:
        print("\n👋 FafyCat development mode stopped.")

if __name__ == "__main__":
    main()
