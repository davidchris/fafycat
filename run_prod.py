#!/usr/bin/env python3
"""Run FafyCat in production mode with real data."""

import os
import subprocess
import sys
from pathlib import Path


def main():
    """Run FafyCat in production mode."""
    # Set production environment
    os.environ["FAFYCAT_DB_URL"] = "sqlite:///data/fafycat_prod.db"
    os.environ["FAFYCAT_ENV"] = "production"

    app_dir = Path(__file__).parent
    streamlit_app = app_dir / "streamlit_app.py"

    print("🐱 Starting FafyCat in PRODUCTION mode")
    print(f"📊 Database: {os.environ['FAFYCAT_DB_URL']}")
    print("💰 Using real transaction data")
    print("⚠️  Make sure you have imported your real data!")
    print("-" * 50)

    try:
        subprocess.run([
            sys.executable, "-m", "streamlit", "run", str(streamlit_app),
            "--server.port", "8502"
        ], cwd=app_dir)
    except KeyboardInterrupt:
        print("\n👋 FafyCat production mode stopped.")

if __name__ == "__main__":
    main()
