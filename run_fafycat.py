#!/usr/bin/env python3
"""CLI entry point for FafyCat."""

import subprocess
import sys
from pathlib import Path


def main():
    """Run FafyCat FastAPI app."""
    app_dir = Path(__file__).parent

    print("🐱 Starting FafyCat (FastAPI + FastHTML)")
    print("🌐 Web UI will be available at: http://localhost:8000")
    print("📚 API docs available at: http://localhost:8000/docs")
    print("-" * 50)

    try:
        subprocess.run([sys.executable, "-m", "uvicorn", "main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"], cwd=app_dir)
    except KeyboardInterrupt:
        print("\n👋 FafyCat app stopped.")


if __name__ == "__main__":
    main()
