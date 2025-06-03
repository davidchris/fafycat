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

    print("🐱 Starting FafyCat in PRODUCTION mode (FastAPI)")
    print(f"📊 Database: {os.environ['FAFYCAT_DB_URL']}")
    print("💰 Using real transaction data")
    print("⚠️  Make sure you have imported your real data!")
    print("🌐 Web UI will be available at: http://localhost:8000")
    print("📚 API docs available at: http://localhost:8000/docs")
    print("-" * 50)

    try:
        subprocess.run(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"], cwd=app_dir
        )
    except KeyboardInterrupt:
        print("\n👋 FafyCat production mode stopped.")


if __name__ == "__main__":
    main()
