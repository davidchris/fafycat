#!/usr/bin/env python3
"""Run FafyCat in production mode with real data."""

import os
import subprocess
import sys
from pathlib import Path


def main():
    """Run FafyCat in production mode."""
    # Set production environment
    os.environ.setdefault("FAFYCAT_DB_URL", "sqlite:///data/fafycat_prod.db")
    os.environ.setdefault("FAFYCAT_ENV", "production")
    os.environ.setdefault("FAFYCAT_PROD_PORT", "8000")
    os.environ.setdefault("FAFYCAT_HOST", "0.0.0.0")

    app_dir = Path(__file__).parent

    print("🐱 Starting FafyCat in PRODUCTION mode (FastAPI)")
    print(f"📊 Database: {os.environ['FAFYCAT_DB_URL']}")
    print("💰 Using real transaction data")
    print("⚠️  Make sure you have imported your real data!")
    port = os.environ.get("FAFYCAT_PROD_PORT", "8000")
    print(f"🌐 Web UI will be available at: http://localhost:{port}")
    print(f"📚 API docs available at: http://localhost:{port}/docs")
    print("-" * 50)

    try:
        port = os.environ.get("FAFYCAT_PROD_PORT", "8000")
        host = os.environ.get("FAFYCAT_HOST", "0.0.0.0")
        subprocess.run([sys.executable, "-m", "uvicorn", "main:app", "--host", host, "--port", port], cwd=app_dir)
    except KeyboardInterrupt:
        print("\n👋 FafyCat production mode stopped.")


if __name__ == "__main__":
    main()
