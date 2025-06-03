#!/usr/bin/env python3
"""CLI entry point for FafyCat."""

import subprocess
import sys
from pathlib import Path


def main():
    """Run FafyCat Streamlit app."""
    app_dir = Path(__file__).parent
    streamlit_app = app_dir / "streamlit_app.py"

    try:
        subprocess.run([
            sys.executable, "-m", "streamlit", "run", str(streamlit_app)
        ], cwd=app_dir)
    except KeyboardInterrupt:
        print("\n👋 FafyCat app stopped.")

if __name__ == "__main__":
    main()
